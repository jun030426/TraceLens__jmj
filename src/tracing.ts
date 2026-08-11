export type VisualizationKind = 'bar_sort' | 'linear_search' | 'binary_search'

export type ArrayElementState =
  | 'default'
  | 'active_neon'
  | 'swapped'
  | 'settled'
  | 'muted'
  | 'found'
  | 'boundary'
  | 'discarded'
  | 'candidate'

export type TraceEventName =
  | 'session_started'
  | 'array_compare'
  | 'array_swap'
  | 'array_scan'
  | 'range_probe'
  | 'range_shrink'
  | 'target_found'
  | 'loop_tick'
  | 'execution_done'
  | 'step_limit_exceeded'

export type TraceVariable = {
  name: string
  type: string
  value: string | number | boolean | null
}

export type TracePointer = {
  name: string
  index: number
  state?: ArrayElementState
}

export type TraceArrayElement = {
  itemId: string
  index: number
  value: number
  state: ArrayElementState
}

export type TraceStructure = {
  id: string
  kind: 'array'
  view: VisualizationKind
  elements: TraceArrayElement[]
  target?: number
  pointers?: TracePointer[]
  window?: {
    left: number
    right: number
    mid?: number
  }
}

export type TraceFrame = {
  type: 'snapshot'
  sessionId: string
  seq: number
  currentLine: number
  algorithm: {
    kind: VisualizationKind
    label: string
  }
  event: {
    name: TraceEventName
    label: string
    targets?: string[]
  }
  variables: TraceVariable[]
  structures: TraceStructure[]
  stdout: string
  callStack: string[]
  compressedRepeat?: number
}

type TraceItem = {
  itemId: string
  value: number
}

type AlgorithmProfile = {
  kind: VisualizationKind
  label: string
}

type ElementBuildOptions = {
  stateByIndex?: Map<number, ArrayElementState>
  activeIndexes?: number[]
  settledFrom?: number
}

const bubbleSortCode = `def bubble_sort(arr):
    n = len(arr)
    for i in range(n):
        for j in range(0, n - i - 1):
            if arr[j] > arr[j + 1]:
                arr[j], arr[j + 1] = arr[j + 1], arr[j]
    return arr

arr = [28, 7, 19, 3, 34, 12, 25, 5]
print(bubble_sort(arr))
`

const linearSearchCode = `def linear_search(arr, target):
    for i, value in enumerate(arr):
        if value == target:
            return i
    return -1

arr = [14, 3, 27, 9, 18, 42, 6, 25]
target = 42
print(linear_search(arr, target))
`

const binarySearchCode = `def binary_search(arr, target):
    left = 0
    right = len(arr) - 1
    while left <= right:
        mid = (left + right) // 2
        if arr[mid] == target:
            return mid
        if arr[mid] < target:
            left = mid + 1
        else:
            right = mid - 1
    return -1

arr = [3, 5, 7, 12, 19, 25, 28, 34, 42]
target = 25
print(binary_search(arr, target))
`

export const algorithmPresets = [
  {
    id: 'bubble_sort',
    label: 'Bubble Sort',
    description: 'swap-heavy bar rendering',
    code: bubbleSortCode,
  },
  {
    id: 'linear_search',
    label: 'Linear Search',
    description: 'single pointer scan rendering',
    code: linearSearchCode,
  },
  {
    id: 'binary_search',
    label: 'Binary Search',
    description: 'range window rendering',
    code: binarySearchCode,
  },
] as const

export const sampleCode = bubbleSortCode

const MAX_VALUES = 24
const MAX_STEPS = 240

const profiles: Record<VisualizationKind, AlgorithmProfile> = {
  bar_sort: {
    kind: 'bar_sort',
    label: 'Sorting',
  },
  linear_search: {
    kind: 'linear_search',
    label: 'Linear Search',
  },
  binary_search: {
    kind: 'binary_search',
    label: 'Binary Search',
  },
}

const findLine = (lines: string[], tests: RegExp[], fallback: number): number => {
  const index = lines.findIndex((line) => tests.some((test) => test.test(line)))
  return index >= 0 ? index + 1 : fallback
}

const extractArray = (code: string) => {
  const matches = [...code.matchAll(/^\s*([A-Za-z_]\w*)\s*=\s*\[([^\]]+)\]/gm)]
  const match = matches.at(-1)

  if (!match) {
    return {
      name: 'arr',
      values: [21, 4, 17, 9, 31, 12, 26, 6],
      detected: false,
    }
  }

  const values = match[2]
    .split(',')
    .map((value) => Number(value.trim()))
    .filter((value) => Number.isFinite(value))
    .slice(0, MAX_VALUES)

  return {
    name: match[1],
    values: values.length > 0 ? values : [21, 4, 17, 9, 31, 12, 26, 6],
    detected: values.length > 0,
  }
}

const extractTarget = (code: string, values: number[]) => {
  const targetAssignment = code.match(/^\s*target\s*=\s*(-?\d+(?:\.\d+)?)/m)

  if (targetAssignment) {
    return Number(targetAssignment[1])
  }

  const functionCall = code.match(
    /\b(?:linear_search|binary_search|search)\s*\(\s*[A-Za-z_]\w*\s*,\s*(-?\d+(?:\.\d+)?)/,
  )

  if (functionCall) {
    return Number(functionCall[1])
  }

  return values[Math.min(Math.floor(values.length * 0.65), values.length - 1)] ?? 0
}

const detectAlgorithm = (code: string): AlgorithmProfile => {
  const lowerCode = code.toLowerCase()

  if (
    /\bbinary_search\b/.test(lowerCode) ||
    (/\bleft\b/.test(lowerCode) && /\bright\b/.test(lowerCode) && /\bmid\b/.test(lowerCode))
  ) {
    return profiles.binary_search
  }

  if (
    /\blinear_search\b/.test(lowerCode) ||
    (/\btarget\b/.test(lowerCode) && /\bfor\b/.test(lowerCode) && !/\bmid\b/.test(lowerCode))
  ) {
    return profiles.linear_search
  }

  return profiles.bar_sort
}

const createItems = (arrayName: string, values: number[]): TraceItem[] =>
  values.map((value, index) => ({
    itemId: `${arrayName}_${index}_${value}`,
    value,
  }))

const buildElements = (
  items: TraceItem[],
  {
    activeIndexes = [],
    settledFrom = Number.POSITIVE_INFINITY,
    stateByIndex = new Map<number, ArrayElementState>(),
  }: ElementBuildOptions = {},
): TraceArrayElement[] =>
  items.map((item, index) => {
    let state: ArrayElementState = 'default'

    if (index >= settledFrom) {
      state = 'settled'
    }

    if (activeIndexes.includes(index)) {
      state = 'active_neon'
    }

    state = stateByIndex.get(index) ?? state

    return {
      itemId: item.itemId,
      index,
      value: item.value,
      state,
    }
  })

const makeFrame = ({
  seq,
  currentLine,
  profile,
  eventName,
  eventLabel,
  targets,
  arrayName,
  items,
  variables,
  stdout = '',
  callStack,
  activeIndexes = [],
  settledFrom,
  stateByIndex,
  pointers,
  target,
  window,
  compressedRepeat,
}: {
  seq: number
  currentLine: number
  profile: AlgorithmProfile
  eventName: TraceEventName
  eventLabel: string
  targets?: string[]
  arrayName: string
  items: TraceItem[]
  variables: TraceVariable[]
  stdout?: string
  callStack: string[]
  activeIndexes?: number[]
  settledFrom?: number
  stateByIndex?: Map<number, ArrayElementState>
  pointers?: TracePointer[]
  target?: number
  window?: TraceStructure['window']
  compressedRepeat?: number
}): TraceFrame => ({
  type: 'snapshot',
  sessionId: 'local-preview-session',
  seq,
  currentLine,
  algorithm: profile,
  event: {
    name: eventName,
    label: eventLabel,
    targets,
  },
  variables,
  structures: [
    {
      id: arrayName,
      kind: 'array',
      view: profile.kind,
      elements: buildElements(items, { activeIndexes, settledFrom, stateByIndex }),
      target,
      pointers,
      window,
    },
  ],
  stdout,
  callStack,
  compressedRepeat,
})

const buildSortTrace = ({
  lines,
  arrayName,
  values,
  detected,
}: {
  lines: string[]
  arrayName: string
  values: number[]
  detected: boolean
}): TraceFrame[] => {
  const profile = profiles.bar_sort
  const items = createItems(arrayName, values)
  const assignLine = findLine(lines, [new RegExp(`^\\s*${arrayName}\\s*=`)], 1)
  const outerLoopLine = findLine(lines, [/\bfor\s+\w+\s+in\s+range\b/], 3)
  const innerLoopLine = findLine(lines, [/\bfor\s+j\s+in\s+range\b/], outerLoopLine)
  const compareLine = findLine(
    lines,
    [/\bif\b.*\[[^\]]+\].*[><=!]=?.*\[[^\]]+\]/],
    innerLoopLine + 1,
  )
  const swapLine = findLine(
    lines,
    [/\[[^\]]+\]\s*,\s*.+\[[^\]]+\]\s*=/, /\w+\[[^\]]+\]\s*=/],
    compareLine + 1,
  )
  const printLine = findLine(lines, [/\bprint\s*\(/], lines.length)

  let seq = 0
  const frames: TraceFrame[] = [
    makeFrame({
      seq: seq++,
      currentLine: assignLine,
      profile,
      eventName: 'session_started',
      eventLabel: detected ? 'array detected as sortable list' : 'demo array loaded',
      arrayName,
      items,
      variables: [
        { name: arrayName, type: 'list[int]', value: `[${values.join(', ')}]` },
      ],
      stdout: detected
        ? `detected ${arrayName}: [${values.join(', ')}]`
        : 'numeric list not found; preview array loaded',
      callStack: ['<module>', 'bubble_sort'],
    }),
  ]

  let clipped = false

  for (let i = 0; i < items.length; i += 1) {
    for (let j = 0; j < items.length - i - 1; j += 1) {
      if (frames.length >= MAX_STEPS) {
        clipped = true
        break
      }

      frames.push(
        makeFrame({
          seq: seq++,
          currentLine: compareLine,
          profile,
          eventName: 'array_compare',
          eventLabel: `${arrayName}[${j}] > ${arrayName}[${j + 1}]`,
          targets: [`${arrayName}[${j}]`, `${arrayName}[${j + 1}]`],
          arrayName,
          items,
          variables: [
            { name: 'i', type: 'int', value: i },
            { name: 'j', type: 'int', value: j },
          ],
          activeIndexes: [j, j + 1],
          settledFrom: items.length - i,
          pointers: [
            { name: 'j', index: j },
            { name: 'j+1', index: j + 1 },
          ],
          callStack: ['<module>', 'bubble_sort'],
        }),
      )

      if (items[j].value > items[j + 1].value) {
        const temp = items[j]
        items[j] = items[j + 1]
        items[j + 1] = temp

        frames.push(
          makeFrame({
            seq: seq++,
            currentLine: swapLine,
            profile,
            eventName: 'array_swap',
            eventLabel: `swap ${arrayName}[${j}], ${arrayName}[${j + 1}]`,
            targets: [`${arrayName}[${j}]`, `${arrayName}[${j + 1}]`],
            arrayName,
            items,
            variables: [
              { name: 'i', type: 'int', value: i },
              { name: 'j', type: 'int', value: j },
            ],
            activeIndexes: [j, j + 1],
            settledFrom: items.length - i,
            pointers: [
              { name: 'j', index: j },
              { name: 'j+1', index: j + 1 },
            ],
            callStack: ['<module>', 'bubble_sort'],
          }),
        )
      }
    }

    if (clipped) {
      break
    }

    frames.push(
      makeFrame({
        seq: seq++,
        currentLine: outerLoopLine,
        profile,
        eventName: 'loop_tick',
        eventLabel: `pass ${i + 1} settled`,
        arrayName,
        items,
        variables: [{ name: 'i', type: 'int', value: i }],
        settledFrom: Math.max(items.length - i - 1, 0),
        compressedRepeat: Math.max(0, items.length - i - 1),
        callStack: ['<module>', 'bubble_sort'],
      }),
    )
  }

  if (clipped) {
    frames.push(
      makeFrame({
        seq: seq++,
        currentLine: innerLoopLine,
        profile,
        eventName: 'step_limit_exceeded',
        eventLabel: 'step limit reached',
        arrayName,
        items,
        variables: [{ name: 'maxSteps', type: 'int', value: MAX_STEPS }],
        compressedRepeat: 1000,
        stdout: `trace clipped at ${MAX_STEPS} steps`,
        callStack: ['<module>', 'bubble_sort'],
      }),
    )
  }

  frames.push(
    makeFrame({
      seq,
      currentLine: printLine,
      profile,
      eventName: 'execution_done',
      eventLabel: 'sorted output ready',
      arrayName,
      items,
      variables: [
        {
          name: arrayName,
          type: 'list[int]',
          value: `[${items.map((item) => item.value).join(', ')}]`,
        },
      ],
      stdout: `[${items.map((item) => item.value).join(', ')}]`,
      activeIndexes: items.map((_, index) => index),
      settledFrom: 0,
      callStack: ['<module>', 'bubble_sort'],
    }),
  )

  return frames
}

const buildLinearSearchTrace = ({
  lines,
  arrayName,
  values,
  detected,
  target,
}: {
  lines: string[]
  arrayName: string
  values: number[]
  detected: boolean
  target: number
}): TraceFrame[] => {
  const profile = profiles.linear_search
  const items = createItems(arrayName, values)
  const assignLine = findLine(lines, [new RegExp(`^\\s*${arrayName}\\s*=`)], 1)
  const loopLine = findLine(lines, [/\bfor\b.*\benumerate\b/, /\bfor\b.*\bin\b/], 2)
  const compareLine = findLine(lines, [/\bif\b.*(?:==|is)\s*target/, /\bif\b.*target/], loopLine + 1)
  const returnLine = findLine(lines, [/\breturn\s+\w+/, /\breturn\s+-?1/], compareLine + 1)
  const printLine = findLine(lines, [/\bprint\s*\(/], lines.length)
  const foundIndex = items.findIndex((item) => item.value === target)
  let seq = 0

  const frames: TraceFrame[] = [
    makeFrame({
      seq: seq++,
      currentLine: assignLine,
      profile,
      eventName: 'session_started',
      eventLabel: detected ? 'array detected as searchable list' : 'demo array loaded',
      arrayName,
      items,
      target,
      variables: [
        { name: arrayName, type: 'list[int]', value: `[${values.join(', ')}]` },
        { name: 'target', type: 'int', value: target },
      ],
      stdout: detected
        ? `detected ${arrayName}: [${values.join(', ')}], target=${target}`
        : `preview search target=${target}`,
      callStack: ['<module>', 'linear_search'],
    }),
  ]

  for (let i = 0; i < items.length; i += 1) {
    const stateByIndex = new Map<number, ArrayElementState>()

    for (let discarded = 0; discarded < i; discarded += 1) {
      stateByIndex.set(discarded, 'discarded')
    }

    stateByIndex.set(i, items[i].value === target ? 'found' : 'active_neon')

    frames.push(
      makeFrame({
        seq: seq++,
        currentLine: compareLine,
        profile,
        eventName: items[i].value === target ? 'target_found' : 'array_scan',
        eventLabel:
          items[i].value === target
            ? `${arrayName}[${i}] matches target ${target}`
            : `scan ${arrayName}[${i}] against target ${target}`,
        targets: [`${arrayName}[${i}]`, 'target'],
        arrayName,
        items,
        target,
        variables: [
          { name: 'i', type: 'int', value: i },
          { name: 'value', type: 'int', value: items[i].value },
          { name: 'target', type: 'int', value: target },
        ],
        stateByIndex,
        pointers: [{ name: 'i', index: i }],
        callStack: ['<module>', 'linear_search'],
      }),
    )

    if (items[i].value === target) {
      break
    }
  }

  const finalState = new Map<number, ArrayElementState>()
  items.forEach((_, index) => {
    if (foundIndex >= 0 && index === foundIndex) {
      finalState.set(index, 'found')
      return
    }

    finalState.set(index, foundIndex >= 0 && index > foundIndex ? 'muted' : 'discarded')
  })

  frames.push(
    makeFrame({
      seq,
      currentLine: foundIndex >= 0 ? returnLine : printLine,
      profile,
      eventName: 'execution_done',
      eventLabel: foundIndex >= 0 ? `target found at index ${foundIndex}` : 'target not found',
      arrayName,
      items,
      target,
      variables: [
        { name: 'target', type: 'int', value: target },
        { name: 'result', type: 'int', value: foundIndex },
      ],
      stateByIndex: finalState,
      pointers: foundIndex >= 0 ? [{ name: 'hit', index: foundIndex }] : [],
      stdout: String(foundIndex),
      callStack: ['<module>', 'linear_search'],
    }),
  )

  return frames
}

const buildBinarySearchTrace = ({
  lines,
  arrayName,
  values,
  detected,
  target,
}: {
  lines: string[]
  arrayName: string
  values: number[]
  detected: boolean
  target: number
}): TraceFrame[] => {
  const profile = profiles.binary_search
  const items = createItems(arrayName, values)
  const assignLine = findLine(lines, [new RegExp(`^\\s*${arrayName}\\s*=`)], 1)
  const whileLine = findLine(lines, [/\bwhile\b.*left.*right/, /\bwhile\b/], 4)
  const midLine = findLine(lines, [/\bmid\s*=/], whileLine + 1)
  const compareLine = findLine(lines, [/\bif\b.*\[mid\].*(==|<|>).*target/], midLine + 1)
  const printLine = findLine(lines, [/\bprint\s*\(/], lines.length)
  const sortedItems = [...items].sort((a, b) => a.value - b.value)
  const sortedValues = sortedItems.map((item) => item.value)

  let left = 0
  let right = sortedItems.length - 1
  let seq = 0
  let foundIndex = -1

  const frames: TraceFrame[] = [
    makeFrame({
      seq: seq++,
      currentLine: assignLine,
      profile,
      eventName: 'session_started',
      eventLabel: detected
        ? 'array detected as searchable sorted list'
        : 'demo sorted array loaded',
      arrayName,
      items: sortedItems,
      target,
      variables: [
        { name: arrayName, type: 'list[int]', value: `[${sortedValues.join(', ')}]` },
        { name: 'target', type: 'int', value: target },
      ],
      stdout: detected
        ? `detected ${arrayName}: [${values.join(', ')}], target=${target}`
        : `preview binary target=${target}`,
      callStack: ['<module>', 'binary_search'],
    }),
  ]

  while (left <= right && frames.length < MAX_STEPS) {
    const mid = Math.floor((left + right) / 2)
    const midValue = sortedItems[mid].value
    const stateByIndex = new Map<number, ArrayElementState>()

    sortedItems.forEach((_, index) => {
      if (index < left || index > right) {
        stateByIndex.set(index, 'discarded')
      } else {
        stateByIndex.set(index, 'candidate')
      }
    })

    stateByIndex.set(left, 'boundary')
    stateByIndex.set(right, 'boundary')
    stateByIndex.set(mid, midValue === target ? 'found' : 'active_neon')

    frames.push(
      makeFrame({
        seq: seq++,
        currentLine: compareLine,
        profile,
        eventName: midValue === target ? 'target_found' : 'range_probe',
        eventLabel:
          midValue === target
            ? `mid ${mid} matches target ${target}`
            : `probe mid ${mid}: ${midValue}`,
        targets: [`${arrayName}[${mid}]`, 'target'],
        arrayName,
        items: sortedItems,
        target,
        variables: [
          { name: 'left', type: 'int', value: left },
          { name: 'mid', type: 'int', value: mid },
          { name: 'right', type: 'int', value: right },
          { name: 'target', type: 'int', value: target },
        ],
        stateByIndex,
        pointers: [
          { name: 'L', index: left },
          { name: 'M', index: mid },
          { name: 'R', index: right },
        ],
        window: { left, right, mid },
        callStack: ['<module>', 'binary_search'],
      }),
    )

    if (midValue === target) {
      foundIndex = mid
      break
    }

    if (midValue < target) {
      left = mid + 1
    } else {
      right = mid - 1
    }

    frames.push(
      makeFrame({
        seq: seq++,
        currentLine: whileLine,
        profile,
        eventName: 'range_shrink',
        eventLabel: `search window -> ${left}..${right}`,
        arrayName,
        items: sortedItems,
        target,
        variables: [
          { name: 'left', type: 'int', value: left },
          { name: 'right', type: 'int', value: right },
        ],
        stateByIndex,
        pointers: [
          { name: 'L', index: Math.max(0, Math.min(left, sortedItems.length - 1)) },
          { name: 'R', index: Math.max(0, Math.min(right, sortedItems.length - 1)) },
        ],
        window: { left, right },
        compressedRepeat: Math.max(0, right - left + 1),
        callStack: ['<module>', 'binary_search'],
      }),
    )
  }

  const finalState = new Map<number, ArrayElementState>()
  sortedItems.forEach((_, index) => {
    finalState.set(index, foundIndex === index ? 'found' : 'discarded')
  })

  frames.push(
    makeFrame({
      seq,
      currentLine: printLine,
      profile,
      eventName: 'execution_done',
      eventLabel: foundIndex >= 0 ? `target found at index ${foundIndex}` : 'target not found',
      arrayName,
      items: sortedItems,
      target,
      variables: [
        { name: 'target', type: 'int', value: target },
        { name: 'result', type: 'int', value: foundIndex },
      ],
      stateByIndex: finalState,
      pointers: foundIndex >= 0 ? [{ name: 'hit', index: foundIndex }] : [],
      stdout: String(foundIndex),
      callStack: ['<module>', 'binary_search'],
    }),
  )

  return frames
}

export const buildPreviewTrace = (code: string): TraceFrame[] => {
  const lines = code.split(/\r?\n/)
  const { name: arrayName, values, detected } = extractArray(code)
  const profile = detectAlgorithm(code)
  const target = extractTarget(code, values)

  if (profile.kind === 'linear_search') {
    return buildLinearSearchTrace({ lines, arrayName, values, detected, target })
  }

  if (profile.kind === 'binary_search') {
    return buildBinarySearchTrace({ lines, arrayName, values, detected, target })
  }

  return buildSortTrace({ lines, arrayName, values, detected })
}
