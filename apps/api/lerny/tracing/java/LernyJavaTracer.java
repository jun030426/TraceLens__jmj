import com.sun.jdi.*;
import com.sun.jdi.connect.Connector;
import com.sun.jdi.connect.LaunchingConnector;
import com.sun.jdi.event.*;
import com.sun.jdi.request.*;

import java.io.File;
import java.io.InputStream;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.util.*;

/**
 * Learning-only Java tracer (docs/06: Java는 JDI). Runs the student's compiled classes in a
 * debuggee VM and prints one JSON object per stop to stdout. It only reads frames and fields;
 * it never invokes toString/getters or any other debuggee method.
 *
 * Usage: java LernyJavaTracer <classDir> <mainClass> <maxSteps> <heapMb>
 */
public class LernyJavaTracer {
    static final int MAX_ITEMS = 20;
    static final int MAX_DEPTH = 3;
    static final String[] EXCLUDE = {"java.*", "javax.*", "sun.*", "jdk.*", "com.sun.*"};

    final PrintStream out = new PrintStream(System.out, true, StandardCharsets.UTF_8);
    final Set<String> userClasses = new HashSet<>();
    final Map<Long, Integer> objectIds = new HashMap<>();
    final Deque<int[]> stack = new ArrayDeque<>(); // [frameId, depth]
    final List<String> stackFuncs = new ArrayList<>();
    int nextFrame = 0;
    int steps = 0;
    int maxSteps;
    InputStream debuggeeOut;
    ThreadReference mainThread;
    StepRequest stepRequest;
    String uncaught;
    Method lastMethod;
    int lastLine = -1;
    long lastIndex = -1;
    int lastDepth = -1;

    public static void main(String[] args) throws Exception {
        new LernyJavaTracer().run(args[0], args[1], Integer.parseInt(args[2]), args[3]);
    }

    void run(String classDir, String mainClass, int maxSteps, String heapMb) throws Exception {
        this.maxSteps = maxSteps;
        collectUserClasses(new File(classDir), "");
        LaunchingConnector connector = Bootstrap.virtualMachineManager().defaultConnector();
        Map<String, Connector.Argument> cargs = connector.defaultArguments();
        cargs.get("main").setValue(mainClass);
        cargs.get("options").setValue("-cp " + classDir + " -Xmx" + heapMb + "m -Xss8m -Dfile.encoding=UTF-8");
        VirtualMachine vm = connector.launch(cargs);
        debuggeeOut = vm.process().getInputStream();
        drainLater(vm.process().getErrorStream());
        EventRequestManager erm = vm.eventRequestManager();
        for (String cls : userClasses) {
            MethodEntryRequest entry = erm.createMethodEntryRequest();
            entry.addClassFilter(cls);
            entry.setSuspendPolicy(EventRequest.SUSPEND_EVENT_THREAD);
            entry.enable();
            MethodExitRequest exit = erm.createMethodExitRequest();
            exit.addClassFilter(cls);
            exit.setSuspendPolicy(EventRequest.SUSPEND_EVENT_THREAD);
            exit.enable();
        }
        ExceptionRequest exc = erm.createExceptionRequest(null, true, true);
        exc.setSuspendPolicy(EventRequest.SUSPEND_EVENT_THREAD);
        exc.enable();

        EventQueue queue = vm.eventQueue();
        boolean done = false;
        while (!done) {
            EventSet set = queue.remove();
            for (Event event : set) {
                if (event instanceof VMDeathEvent || event instanceof VMDisconnectEvent) {
                    done = true;
                    continue;
                }
                if (steps >= maxSteps) {
                    emitEnd(true);
                    vm.exit(0);
                    return;
                }
                try {
                    handle(event, erm);
                } catch (IncompatibleThreadStateException | AbsentInformationException ignored) {
                    // a frame we cannot read is simply not reported
                }
            }
            if (!done) set.resume();
        }
        emitEnd(false);
    }

    void handle(Event event, EventRequestManager erm) throws Exception {
        if (!(event instanceof LocatableEvent le)) return;
        ThreadReference thread = le.thread();
        if (mainThread == null && event instanceof MethodEntryEvent && thread.name().equals("main")) {
            mainThread = thread;
            stepRequest = erm.createStepRequest(thread, StepRequest.STEP_MIN, StepRequest.STEP_INTO);
            for (String ex : EXCLUDE) stepRequest.addClassExclusionFilter(ex);
            stepRequest.setSuspendPolicy(EventRequest.SUSPEND_EVENT_THREAD);
            stepRequest.enable();
        }
        if (thread != mainThread) return;
        List<StackFrame> frames = userFrames(thread);
        if (event instanceof MethodEntryEvent) {
            if (frames.isEmpty()) return;
            syncDown(frames.size() - 1, frames);
            push(frames);
            emit("call", frames.get(frames.size() - 1), null, null);
        } else if (event instanceof MethodExitEvent mx) {
            if (frames.isEmpty() || stack.size() != frames.size()) return;
            Value rv = mx.method().returnTypeName().equals("void") ? null : mx.returnValue();
            emit("return", frames.get(frames.size() - 1), null, rv == null ? null : rv);
            pop();
            if (frames.size() >= 2) {
                // back in the caller mid-line after the call: that line is not a new stop
                Location caller = frames.get(frames.size() - 2).location();
                lastMethod = caller.method();
                lastLine = caller.lineNumber();
                lastIndex = caller.codeIndex();
                lastDepth = frames.size() - 1;
            }
        } else if (event instanceof StepEvent se) {
            if (frames.isEmpty()) return;
            // STEP_MIN (not STEP_LINE): a loop whose body sits on one line would otherwise never
            // finish a line step. Report a stop when the line changes or the code jumps back.
            Location loc = se.location();
            boolean sameMethod = lastMethod != null && lastMethod.equals(loc.method()) && lastDepth == frames.size();
            boolean newStop = !sameMethod || loc.lineNumber() != lastLine || loc.codeIndex() < lastIndex;
            lastMethod = loc.method();
            lastLine = loc.lineNumber();
            lastIndex = loc.codeIndex();
            lastDepth = frames.size();
            if (!newStop) return;
            syncDown(frames.size(), frames);
            while (stack.size() < frames.size()) push(frames.subList(0, stack.size() + 1));
            emit("line", frames.get(frames.size() - 1), null, null);
        } else if (event instanceof ExceptionEvent ee) {
            boolean thrownHere = isUser(ee.location().declaringType().name());
            Location catchAt = ee.catchLocation();
            boolean caughtHere = catchAt != null && isUser(catchAt.declaringType().name());
            if (!thrownHere && !caughtHere && catchAt != null) return; // JDK-internal noise
            if (frames.isEmpty()) return;
            String message = describeException(ee.exception());
            if (catchAt == null) uncaught = message;
            syncDown(frames.size(), frames);
            emit("exception", frames.get(frames.size() - 1), message, null);
        }
    }

    // Our frame model follows the real user stack; frames that vanish (exception unwinding)
    // are closed without inventing a return value.
    void syncDown(int keep, List<StackFrame> frames) throws Exception {
        while (stack.size() > keep) {
            StackFrame f = frames.isEmpty() ? null : frames.get(Math.min(stack.size(), frames.size()) - 1);
            int[] top = stack.peek();
            emitRaw("return", top[0], parentOf(), stackFuncs.get(stackFuncs.size() - 1),
                    f == null ? 0 : f.location().lineNumber(), "null", "{}", null, null);
            pop();
        }
    }

    void push(List<StackFrame> frames) {
        StackFrame f = frames.get(frames.size() - 1);
        stack.push(new int[]{nextFrame++, frames.size()});
        stackFuncs.add(f.location().method().name());
    }

    void pop() {
        stack.pop();
        stackFuncs.remove(stackFuncs.size() - 1);
    }

    Integer parentOf() {
        if (stack.size() < 2) return null;
        Iterator<int[]> it = stack.iterator();
        it.next();
        return it.next()[0];
    }

    List<StackFrame> userFrames(ThreadReference thread) throws IncompatibleThreadStateException {
        List<StackFrame> all = thread.frames();
        List<StackFrame> user = new ArrayList<>();
        for (int i = all.size() - 1; i >= 0; i--) {
            StackFrame f = all.get(i);
            if (isUser(f.location().declaringType().name())) user.add(f);
        }
        return user; // outermost first
    }

    boolean isUser(String className) {
        return userClasses.contains(className);
    }

    void emit(String kind, StackFrame frame, String error, Value returned) throws Exception {
        Map<Integer, String> objects = new LinkedHashMap<>();
        StringBuilder locals = new StringBuilder("{");
        boolean first = true;
        boolean isMain = stack.size() == 1;
        try {
            ObjectReference self = frame.thisObject();
            if (self != null) {
                locals.append(q("this")).append(':').append(value(self, objects, 0));
                first = false;
            }
            for (LocalVariable v : frame.visibleVariables()) {
                if (isMain && v.isArgument() && v.typeName().equals("java.lang.String[]")) continue;
                if (!first) locals.append(',');
                locals.append(q(v.name())).append(':').append(value(frame.getValue(v), objects, 0));
                first = false;
            }
        } catch (AbsentInformationException ignored) {
            // compiled without -g; the runner always passes -g
        }
        locals.append('}');
        String ret = returned == null ? null : value(returned, objects, 0);
        StringBuilder objs = new StringBuilder("{");
        first = true;
        for (Map.Entry<Integer, String> e : objects.entrySet()) {
            if (!first) objs.append(',');
            objs.append(q(String.valueOf(e.getKey()))).append(':').append(e.getValue());
            first = false;
        }
        objs.append('}');
        int[] top = stack.peek();
        emitRaw(kind, top[0], parentOf(), frame.location().method().name(),
                frame.location().lineNumber(), locals.toString(), objs.toString(), error, ret);
    }

    void emitRaw(String kind, int fid, Integer parent, String func, int line, String locals,
                 String objects, String error, String returned) throws Exception {
        steps++;
        StringBuilder sb = new StringBuilder("{");
        sb.append("\"kind\":").append(q(kind));
        sb.append(",\"fid\":").append(fid);
        sb.append(",\"parent\":").append(parent == null ? "null" : parent.toString());
        sb.append(",\"func\":").append(q(func));
        sb.append(",\"line\":").append(line);
        sb.append(",\"locals\":").append(locals);
        sb.append(",\"objects\":").append(objects);
        sb.append(",\"stdout\":").append(q(readStdout()));
        if (error != null) sb.append(",\"error\":").append(q(error));
        if (returned != null) sb.append(",\"returned\":").append(returned);
        sb.append('}');
        out.println(sb);
    }

    void emitEnd(boolean clipped) throws Exception {
        String tail = readStdout();
        out.println("{\"kind\":\"end\",\"clipped\":" + clipped + ",\"stdout\":" + q(tail)
                + ",\"error\":" + (uncaught == null ? "null" : q(uncaught)) + "}");
    }

    String readStdout() throws Exception {
        int n = debuggeeOut.available();
        if (n <= 0) return "";
        byte[] buf = debuggeeOut.readNBytes(Math.min(n, 65536));
        return new String(buf, StandardCharsets.UTF_8);
    }

    // ── values: read-only, no debuggee method invocation ──

    String value(Value v, Map<Integer, String> objects, int depth) {
        if (v == null) return prim("null", "null");
        if (v instanceof BooleanValue b) return prim(String.valueOf(b.value()), "bool");
        if (v instanceof CharValue c) return prim("'" + c.value() + "'", "char");
        if (v instanceof IntegerValue || v instanceof LongValue || v instanceof ShortValue || v instanceof ByteValue)
            return prim(v.toString(), "int");
        if (v instanceof DoubleValue d) return prim(String.valueOf(d.value()), "float");
        if (v instanceof FloatValue f) return prim(String.valueOf(f.value()), "float");
        if (v instanceof StringReference s) return prim("\"" + s.value() + "\"", "str");
        if (!(v instanceof ObjectReference o)) return prim("?", "unsupported");
        String type = o.referenceType().name();
        if (isBoxed(type)) {
            Field field = o.referenceType().fieldByName("value");
            if (field != null) return value(o.getValue(field), objects, depth);
        }
        int id = objectIds.computeIfAbsent(o.uniqueID(), k -> objectIds.size() + 1);
        String ref = "{\"k\":\"ref\",\"id\":" + id + "}";
        if (objects.containsKey(id)) return ref;
        if (depth > MAX_DEPTH) {
            objects.put(id, "{\"id\":" + id + ",\"type\":" + q(simple(type)) + ",\"truncated\":true}");
            return ref;
        }
        objects.put(id, ""); // reserve against cycles
        if (o instanceof ArrayReference a) {
            objects.put(id, listSnap(id, "list", a.getValues(0, Math.min(a.length(), MAX_ITEMS)), a.length(), objects, depth));
        } else if (type.equals("java.util.ArrayList")) {
            ArrayReference data = (ArrayReference) o.getValue(o.referenceType().fieldByName("elementData"));
            int size = ((IntegerValue) o.getValue(o.referenceType().fieldByName("size"))).value();
            List<Value> items = data == null ? List.of() : data.getValues(0, Math.min(size, MAX_ITEMS));
            objects.put(id, listSnap(id, "list", items, size, objects, depth));
        } else if (isUser(type)) {
            StringBuilder sb = new StringBuilder("{\"id\":" + id + ",\"type\":" + q(simple(type)) + ",\"entries\":[");
            boolean first = true;
            int count = 0;
            for (Field field : o.referenceType().allFields()) {
                if (field.isStatic() || field.isSynthetic()) continue;
                if (count++ >= MAX_ITEMS) break;
                if (!first) sb.append(',');
                sb.append('[').append(q(field.name())).append(',').append(value(o.getValue(field), objects, depth + 1)).append(']');
                first = false;
            }
            objects.put(id, sb.append("]}").toString());
        } else {
            objects.put(id, "{\"id\":" + id + ",\"type\":" + q(simple(type)) + ",\"unsupported\":true}");
        }
        return ref;
    }

    String listSnap(int id, String type, List<Value> items, int n, Map<Integer, String> objects, int depth) {
        StringBuilder sb = new StringBuilder("{\"id\":" + id + ",\"type\":" + q(type) + ",\"items\":[");
        for (int i = 0; i < items.size(); i++) {
            if (i > 0) sb.append(',');
            sb.append(value(items.get(i), objects, depth + 1));
        }
        return sb.append("],\"n\":").append(n).append(",\"truncated\":").append(n > MAX_ITEMS).append('}').toString();
    }

    String describeException(ObjectReference exc) {
        String name = simple(exc.referenceType().name());
        Field f = exc.referenceType().fieldByName("detailMessage");
        Value m = f == null ? null : exc.getValue(f);
        return m instanceof StringReference s ? name + ": " + s.value() : name;
    }

    static boolean isBoxed(String t) {
        return switch (t) {
            case "java.lang.Integer", "java.lang.Long", "java.lang.Short", "java.lang.Byte",
                 "java.lang.Double", "java.lang.Float", "java.lang.Boolean", "java.lang.Character" -> true;
            default -> false;
        };
    }

    static String simple(String t) {
        int i = Math.max(t.lastIndexOf('.'), t.lastIndexOf('$'));
        return i >= 0 ? t.substring(i + 1) : t;
    }

    static String prim(String text, String type) {
        if (text.length() > 80) text = text.substring(0, 80) + "…";
        return "{\"k\":\"prim\",\"v\":" + q(text) + ",\"t\":" + q(type) + "}";
    }

    static String q(String s) {
        StringBuilder sb = new StringBuilder("\"");
        for (char c : s.toCharArray()) {
            switch (c) {
                case '"' -> sb.append("\\\"");
                case '\\' -> sb.append("\\\\");
                case '\n' -> sb.append("\\n");
                case '\r' -> sb.append("\\r");
                case '\t' -> sb.append("\\t");
                default -> {
                    if (c < 0x20) sb.append(String.format("\\u%04x", (int) c));
                    else sb.append(c);
                }
            }
        }
        return sb.append('"').toString();
    }

    void collectUserClasses(File dir, String pkg) {
        File[] files = dir.listFiles();
        if (files == null) return;
        for (File f : files) {
            if (f.isDirectory()) collectUserClasses(f, pkg + f.getName() + ".");
            else if (f.getName().endsWith(".class"))
                userClasses.add(pkg + f.getName().substring(0, f.getName().length() - 6));
        }
    }

    static void drainLater(InputStream in) {
        Thread t = new Thread(() -> {
            try {
                in.transferTo(java.io.OutputStream.nullOutputStream());
            } catch (Exception ignored) {
            }
        });
        t.setDaemon(true);
        t.start();
    }
}
