import { describe, it, expect } from 'vitest'
import { compose, LINGER } from './compose'
import type { Shot, StagePlan } from './types'
import type { StageLayout } from './layout'

const plan: StagePlan = {
  objects: [
    { objectId: 1, type: 'list', life: { from: 0, to: 99 }, maxItems: 4, changeCount: 3, referencedBy: ['0:a'], slot: 0 },
    { objectId: 2, type: 'list', life: { from: 0, to: 99 }, maxItems: 4, changeCount: 3, referencedBy: ['0:b'], slot: 1 },
  ],
  variables: [
    { varKey: '0:a', frameId: 0, name: 'a', life: { from: 0, to: 99 }, holdsRef: true },
    { varKey: '0:b', frameId: 0, name: 'b', life: { from: 0, to: 99 }, holdsRef: true },
    { varKey: '0:i', frameId: 0, name: 'i', life: { from: 0, to: 99 }, holdsRef: false },
  ],
  frames: [{ frameId: 0, func: '<module>', parentFrameId: null, life: { from: 0, to: 99 }, depth: 0, recursionIndex: 0 }],
  slotCount: 2, maxStackDepth: 1, maxListLength: 4, leadObjectId: 1,
}
const layout: StageLayout = {
  width: 1200, height: 640, cellW: 40,
  objPos: new Map([
    [1, { x: 560, y: 70, w: 300, h: 64 }],
    [2, { x: 560, y: 182, w: 300, h: 64 }],
  ]),
  varPos: new Map(),
  framePos: new Map(),
}
const shot = (seq: number, motions: Shot['motions']): Shot => ({ seq, motions, durationMs: 520, focus: null })

describe('compose', () => {
  it('이번 샷에 닿은 배우는 포커스(중앙·배율 1), 안 닿은 최근 배우는 대기(축소)', () => {
    const shots = [
      shot(0, [{ v: 'grow', objectId: 1, index: 0, text: '1' }]),
      shot(1, [{ v: 'grow', objectId: 2, index: 0, text: '2' }]),
      shot(2, [{ v: 'grow', objectId: 2, index: 1, text: '3' }]), // 마지막 샷(커튼콜)을 피해 중간 샷을 검증
    ]
    const { comps } = compose(shots, plan, layout)
    const c1 = comps[1]
    expect(c1.get('o2')!.focus).toBe(true)
    expect(c1.get('o2')!.s).toBe(1)
    expect(c1.get('o1')!.focus).toBe(false)
    expect(c1.get('o1')!.s).toBeLessThan(1)
    expect(c1.get('o1')!.x).toBeGreaterThan(c1.get('o2')!.x) // 대기열은 오른쪽
  })

  it('LINGER를 넘긴 배우는 무대에서 빠진다 (커튼콜 전까지)', () => {
    const shots = [
      shot(0, [{ v: 'grow', objectId: 1, index: 0, text: '1' }]),
      ...Array.from({ length: LINGER + 2 }, (_, k) => shot(k + 1, [{ v: 'setVar', varKey: '0:i', text: String(k) }])),
    ]
    const { comps } = compose(shots, plan, layout)
    expect(comps[LINGER + 1].has('o1')).toBe(false) // 유예가 끝나면 중간 샷에서는 내려간다
    expect(comps[LINGER].has('o1')).toBe(true) // 마지막 유예 샷까지는 남는다
    expect(comps[comps.length - 1].has('o1')).toBe(true) // 커튼콜 — 살아있으니 최종 상태로 복귀
  })

  it('변수는 좌측 스트립 — 닿은 것이 포커스', () => {
    const shots = [shot(0, [{ v: 'setVar', varKey: '0:i', text: '3' }])]
    const { comps } = compose(shots, plan, layout)
    const v = comps[0].get('v0:i')!
    expect(v.focus).toBe(true)
    expect(v.x).toBeLessThan(560)
  })

  it('같은 열 안에서 세로로 겹치지 않는다', () => {
    const shots = [
      shot(0, [
        { v: 'grow', objectId: 1, index: 0, text: '1' },
        { v: 'grow', objectId: 2, index: 0, text: '2' },
      ]),
    ]
    const { comps } = compose(shots, plan, layout)
    const a = comps[0].get('o1')!
    const b = comps[0].get('o2')!
    const h1 = 64 * a.s
    expect(Math.abs(b.y - a.y)).toBeGreaterThanOrEqual(h1) // 아래 배우가 위 배우 높이 밖
  })

  it('sticky — 계속 무대에 있는 배우는 세로 순서를 유지한다', () => {
    const shots = [
      shot(0, [
        { v: 'grow', objectId: 1, index: 0, text: '1' },
        { v: 'grow', objectId: 2, index: 0, text: '2' },
      ]),
      shot(1, [
        { v: 'setCell', objectId: 2, index: 0, text: '9' },
        { v: 'setCell', objectId: 1, index: 0, text: '8' },
      ]),
    ]
    const { comps } = compose(shots, plan, layout)
    const before = comps[0].get('o1')!.y < comps[0].get('o2')!.y
    const after = comps[1].get('o1')!.y < comps[1].get('o2')!.y
    expect(after).toBe(before)
  })
})

describe('compose: 정리 규칙', () => {
  it('exitObj는 닿음이 아니다 — 죽은 배우는 즉시 무대에서 빠진다', () => {
    const shots = [
      shot(0, [{ v: 'grow', objectId: 1, index: 0, text: '1' }]),
      shot(1, [{ v: 'exitObj', objectId: 1 }, { v: 'setVar', varKey: '0:i', text: '0' }]),
      shot(2, [{ v: 'setVar', varKey: '0:i', text: '1' }]),
    ]
    const { comps } = compose(shots, plan, layout)
    expect(comps[1].has('o1')).toBe(false)
    expect(comps[2].has('o1')).toBe(false)
  })

  it('마지막 샷은 커튼콜 — 무대의 전원이 포커스로 중앙에 선다', () => {
    const shots = [
      shot(0, [{ v: 'grow', objectId: 1, index: 0, text: '1' }]),
      shot(1, [{ v: 'grow', objectId: 2, index: 0, text: '2' }]),
      shot(2, [{ v: 'stdout', text: 'done' }]),
    ]
    const { comps } = compose(shots, plan, layout)
    const last = comps[2]
    expect(last.get('o1')!.focus).toBe(true)
    expect(last.get('o2')!.focus).toBe(true)
    expect(last.get('o1')!.s).toBe(1)
  })
})

describe('compose: 학습자 시선 — 무대 안정성', () => {
  it('변수만 바뀌는 샷에서 직전 포커스 객체는 중앙을 지킨다 (sticky focus)', () => {
    const shots = [
      shot(0, [{ v: 'grow', objectId: 1, index: 0, text: '1' }]),
      shot(1, [{ v: 'setVar', varKey: '0:i', text: '0' }]),
      shot(2, [{ v: 'setVar', varKey: '0:i', text: '1' }]),
      shot(3, [{ v: 'stdout', text: 'x' }]),
    ]
    const { comps } = compose(shots, plan, layout)
    const at0 = comps[0].get('o1')!
    const at1 = comps[1].get('o1')!
    const at2 = comps[2].get('o1')!
    expect(at1.focus).toBe(true)
    expect(at1.s).toBe(1)
    expect(at1.x).toBe(at0.x)
    expect(at1.y).toBe(at0.y)
    expect(at2.x).toBe(at0.x)
  })

  it('살아있는 변수는 LINGER를 넘겨도 무대에 남는다', () => {
    const shots = [
      shot(0, [{ v: 'setVar', varKey: '0:i', text: '0' }]),
      ...Array.from({ length: LINGER + 2 }, (_, k) => shot(k + 1, [{ v: 'setVar', varKey: '0:a', text: String(k) }])),
    ]
    const { comps } = compose(shots, plan, layout)
    expect(comps[comps.length - 2].has('v0:i')).toBe(true)
  })

  it('exitVar된 변수는 즉시 내려가고, 재등장하면 돌아온다', () => {
    const shots = [
      shot(0, [{ v: 'setVar', varKey: '0:i', text: '0' }]),
      shot(1, [{ v: 'exitVar', varKey: '0:i' }, { v: 'setVar', varKey: '0:a', text: '1' }]),
      shot(2, [{ v: 'setVar', varKey: '0:i', text: '9' }]),
      shot(3, [{ v: 'stdout', text: 'x' }]),
    ]
    const { comps } = compose(shots, plan, layout)
    expect(comps[1].has('v0:i')).toBe(false)
    expect(comps[2].has('v0:i')).toBe(true)
  })

  it('상자를 쥔 변수는 알약을 접는다 — 상자 이름표가 대신 말한다', () => {
    const shots = [
      shot(0, [{ v: 'bind', varKey: '0:a', objectId: 1, alias: false }, { v: 'grow', objectId: 1, index: 0, text: '1' }]),
      shot(1, [{ v: 'setVar', varKey: '0:i', text: '0' }]),
      shot(2, [{ v: 'setVar', varKey: '0:a', text: '5' }]), // 프림 재대입 — 알약 복귀
      shot(3, [{ v: 'stdout', text: 'x' }]),
    ]
    const { comps } = compose(shots, plan, layout)
    expect(comps[1].has('v0:a')).toBe(false)
    expect(comps[2].has('v0:a')).toBe(true)
  })

  it('커튼콜에는 살아있는 전원이 돌아온다 — 죽은 배우는 빼고', () => {
    const deadPlan: StagePlan = {
      ...plan,
      objects: [
        { ...plan.objects[0], life: { from: 0, to: 1 } },
        plan.objects[1],
      ],
    }
    const shots = [
      shot(0, [{ v: 'grow', objectId: 1, index: 0, text: '1' }, { v: 'setVar', varKey: '0:i', text: '0' }]),
      shot(1, [{ v: 'exitObj', objectId: 1 }, { v: 'grow', objectId: 2, index: 0, text: '2' }]),
      ...Array.from({ length: LINGER + 1 }, (_, k) => shot(k + 2, [{ v: 'setVar', varKey: '0:a', text: String(k) }])),
      shot(LINGER + 3, [{ v: 'stdout', text: 'done' }]),
    ]
    const { comps } = compose(shots, deadPlan, layout)
    const last = comps[comps.length - 1]
    expect(last.has('o1')).toBe(false)
    expect(last.get('o2')).toBeTruthy()
    expect(last.get('o2')!.focus).toBe(true)
    expect(last.get('v0:i')).toBeTruthy()
    expect(last.get('v0:i')!.focus).toBe(true)
  })
})

describe('compose: 오토 프레이밍', () => {
  it('작은 구성은 확대되고(k>1), 배우가 프레임(1200×640) 안에 담긴다', () => {
    const shots = [shot(0, [{ v: 'grow', objectId: 1, index: 0, text: '1' }])]
    const { comps, cams } = compose(shots, plan, layout)
    const cam = cams[0]
    expect(cam.k).toBeGreaterThan(1)
    expect(cam.k).toBeLessThanOrEqual(1.6)
    const p = comps[0].get('o1')!
    const cx = cam.k * (p.x + 150) + cam.x // 상자(w 300) 중심의 화면 좌표
    const cy = cam.k * (p.y + 32) + cam.y
    expect(cx).toBeGreaterThan(0)
    expect(cx).toBeLessThan(1200)
    expect(cy).toBeGreaterThan(0)
    expect(cy).toBeLessThan(640)
  })

  it('구성이 거의 같으면 카메라를 유지한다 (같은 참조 — 덜덜림 방지)', () => {
    const shots = [
      shot(0, [{ v: 'grow', objectId: 1, index: 0, text: '1' }]),
      shot(1, [{ v: 'setCell', objectId: 1, index: 0, text: '2' }]),
      shot(2, [{ v: 'setCell', objectId: 1, index: 0, text: '3' }]),
    ]
    const { cams } = compose(shots, plan, layout)
    expect(cams[1]).toBe(cams[0])
  })
})

describe('compose: 저울 자리 (scales)', () => {
  const cellCmp = (objectId: number, i: number, k: number): Shot['motions'][number] => ({
    v: 'compare',
    text: '5 > 3 → 참',
    targets: [
      { kind: 'cell', objectId, index: i },
      { kind: 'cell', objectId, index: k },
    ],
    a: '5', op: '>', b: '3', verdict: true,
  })

  it('cell 타깃 비교 — 저울이 두 칸의 화면 중점 위·이름표 띠 위로 내려간다', () => {
    const shots = [
      shot(0, [{ v: 'grow', objectId: 1, index: 0, text: '5' }]),
      shot(1, [cellCmp(1, 0, 1)]),
      shot(2, [{ v: 'stdout', text: 'x' }]),
    ]
    const { comps, cams, scales } = compose(shots, plan, layout)
    const spot = scales[1]!
    expect(spot).toBeTruthy()
    const p = comps[1].get('o1')!
    const cam = cams[1]
    const cellX = (i: number) => cam.x + cam.k * (p.x + (8 + i * 40 + 17) * p.s)
    expect(spot.x).toBeCloseTo((cellX(0) + cellX(1)) / 2, 5)
    expect(spot.y).toBeGreaterThan(36) // 홈 띠보다 아래로 실제로 내려왔다
    const labelTop = cam.y + cam.k * (p.y - 26 * p.s)
    expect(spot.y).toBeCloseTo(labelTop - 8 - 48, 5) // 이름표 띠 위 8px 여백 + 저울 하반부 48
  })

  it('var 전용 비교 — 홈(상단 띠 중앙)에 머문다', () => {
    const shots = [
      shot(0, [{ v: 'setVar', varKey: '0:i', text: '3' }]),
      shot(1, [
        {
          v: 'compare', text: 'i < 5 → 참',
          targets: [{ kind: 'var', varKey: '0:i' }],
          a: '3', op: '<', b: '5', verdict: true,
        },
      ]),
      shot(2, [{ v: 'stdout', text: 'x' }]),
    ]
    const { scales } = compose(shots, plan, layout)
    expect(scales[1]).toEqual({ x: 600, y: 36 })
  })

  it('저울 자리가 위 배우와 겹치면 내려가지 않는다 — 홈 폴백', () => {
    const tallPlan: StagePlan = {
      ...plan,
      objects: [
        ...plan.objects,
        { objectId: 3, type: 'list', life: { from: 0, to: 99 }, maxItems: 4, changeCount: 3, referencedBy: ['0:c'], slot: 2 },
      ],
    }
    const tallLayout: StageLayout = {
      ...layout,
      objPos: new Map([...layout.objPos, [3, { x: 560, y: 294, w: 300, h: 64 }]]),
    }
    const shots = [
      shot(0, [
        { v: 'grow', objectId: 1, index: 0, text: '1' },
        { v: 'grow', objectId: 2, index: 0, text: '2' },
        { v: 'grow', objectId: 3, index: 0, text: '3' },
      ]),
      // 셋 다 무대에 두고 맨 아래 상자의 칸을 비교 — 저울이 내려가면 위 상자와 겹친다
      shot(1, [
        { v: 'setCell', objectId: 1, index: 0, text: '9' },
        { v: 'setCell', objectId: 2, index: 0, text: '8' },
        cellCmp(3, 0, 1),
      ]),
      shot(2, [{ v: 'stdout', text: 'x' }]),
    ]
    const { scales } = compose(shots, tallPlan, tallLayout)
    const spot = scales[1]!
    expect(spot.y).toBe(36) // 홈 띠
    expect(spot.x).toBeGreaterThanOrEqual(366) // 반복 배지(우측 264)를 피한 x
    expect(spot.x).toBeLessThanOrEqual(1030)
  })

  it('강조 샷 — 대상이 화면 중앙에 오고, 프레임 안에 온전히 담기며, 저울과 겹치지 않는다', () => {
    const shots = [
      shot(0, [{ v: 'grow', objectId: 1, index: 0, text: '5' }]),
      shot(1, [cellCmp(1, 0, 1), { v: 'emphasis', k: 1.45 }]),
      shot(2, [{ v: 'stdout', text: 'x' }]),
    ]
    const { comps, cams, scales, autos } = compose(shots, plan, layout)
    const a = autos[1]
    expect(a.k).toBeGreaterThan(1) // 강조가 실제로 걸렸다
    const p = comps[1].get('o1')!
    const cam = cams[1]
    const fx = (v: number) => a.x + a.k * (cam.x + cam.k * v)
    const fy = (v: number) => a.y + a.k * (cam.y + cam.k * v)
    const box = { x0: fx(p.x), x1: fx(p.x + 300 * p.s), y0: fy(p.y - 26 * p.s), y1: fy(p.y + 80 * p.s) }
    // ① 대상 중심이 AREA 중앙 (600, 285)에 온다
    expect((box.x0 + box.x1) / 2).toBeCloseTo(600, 5)
    expect((box.y0 + box.y1) / 2).toBeCloseTo(285, 5)
    // ② 프레임 밖으로 잘리지 않는다 (예전 결함: 오른쪽이 1270까지 나갔다)
    expect(box.x0).toBeGreaterThanOrEqual(0)
    expect(box.x1).toBeLessThanOrEqual(1200)
    expect(box.y0).toBeGreaterThanOrEqual(0)
    expect(box.y1).toBeLessThanOrEqual(640)
    // ③ 저울과 겹치지 않는다
    const spot = scales[1]!
    const sb = { x0: spot.x - 94, x1: spot.x + 162, y0: spot.y - 34, y1: spot.y + 48 }
    const hit = sb.x0 < box.x1 && box.x0 < sb.x1 && sb.y0 < box.y1 && box.y0 < sb.y1
    expect(hit).toBe(false)
  })

  it('대상이 무대에 없으면 강조를 조용히 포기한다 — 없는 것을 당길 수는 없다', () => {
    const shots = [
      shot(0, [{ v: 'setVar', varKey: '0:i', text: '1' }, { v: 'emphasis', k: 1.45 }]),
      shot(1, [{ v: 'stdout', text: 'x' }]),
    ]
    const { autos } = compose(shots, plan, layout)
    expect(autos[0]).toEqual({ k: 1, x: 0, y: 0 })
  })

  it('강조로 화면 밖에 밀려날 배우는 구성에서 빠진다 — 반쯤 잘린 배우를 남기지 않는다', () => {
    const shots = [
      shot(0, [{ v: 'grow', objectId: 1, index: 0, text: '5' }, { v: 'setVar', varKey: '0:i', text: '0' }]),
      shot(1, [cellCmp(1, 0, 1), { v: 'emphasis', k: 1.45 }]),
      shot(2, [{ v: 'setVar', varKey: '0:i', text: '1' }]),
      shot(3, [{ v: 'stdout', text: 'x' }]),
    ]
    const { comps, cams, autos } = compose(shots, plan, layout)
    const a = autos[1]
    expect(a.k).toBeGreaterThan(1)
    // 남아 있는 배우는 전부 프레임 안에 온전히 담긴다
    for (const [key, p] of comps[1]) {
      const size = key[0] === 'o' ? { w: 300, h: 64 } : { w: 190, h: 36 }
      const band = key[0] === 'o' ? { top: 26, bot: 16 } : { top: 0, bot: 0 }
      const fx = (v: number) => a.x + a.k * (cams[1].x + cams[1].k * v)
      const fy = (v: number) => a.y + a.k * (cams[1].y + cams[1].k * v)
      expect(fx(p.x)).toBeGreaterThanOrEqual(0)
      expect(fx(p.x + size.w * p.s)).toBeLessThanOrEqual(1200)
      expect(fy(p.y - band.top * p.s)).toBeGreaterThanOrEqual(0)
      expect(fy(p.y + (size.h + band.bot) * p.s)).toBeLessThanOrEqual(640)
    }
  })

  it('강조 대상은 절대 접히지 않는다 — 볼 것을 지우면 강조가 아니다', () => {
    const shots = [
      shot(0, [{ v: 'grow', objectId: 1, index: 0, text: '5' }, { v: 'setVar', varKey: '0:i', text: '0' }]),
      shot(1, [cellCmp(1, 0, 1), { v: 'emphasis', k: 1.45 }]),
      shot(2, [{ v: 'stdout', text: 'x' }]),
    ]
    const { comps, autos } = compose(shots, plan, layout)
    expect(autos[1].k).toBeGreaterThan(1)
    expect(comps[1].has('o1')).toBe(true)
  })

  it('강조가 없는 샷의 구성은 정리되지 않는다 — 접기는 강조의 대가일 뿐이다', () => {
    const shots = [
      shot(0, [{ v: 'grow', objectId: 1, index: 0, text: '5' }, { v: 'setVar', varKey: '0:i', text: '0' }]),
      shot(1, [{ v: 'setVar', varKey: '0:i', text: '1' }]),
      shot(2, [{ v: 'stdout', text: 'x' }]),
    ]
    const { comps, autos } = compose(shots, plan, layout)
    expect(autos[1]).toEqual({ k: 1, x: 0, y: 0 })
    expect(comps[1].has('o1')).toBe(true)
    expect(comps[1].has('v0:i')).toBe(true)
  })

  it('강조가 없는 샷의 카메라는 항등 — 강조는 한 비트만 산다', () => {
    const shots = [
      shot(0, [{ v: 'grow', objectId: 1, index: 0, text: '5' }]),
      shot(1, [cellCmp(1, 0, 1), { v: 'emphasis', k: 1.45 }]),
      shot(2, [cellCmp(1, 1, 2)]),
      shot(3, [{ v: 'stdout', text: 'x' }]),
    ]
    const { autos } = compose(shots, plan, layout)
    expect(autos[0]).toEqual({ k: 1, x: 0, y: 0 })
    expect(autos[1].k).toBeGreaterThan(1)
    expect(autos[2]).toEqual({ k: 1, x: 0, y: 0 })
  })

  it('비교 연속 구간의 사이 샷에도 자리가 유지되고, 구간이 끝나면 사라진다', () => {
    const shots = [
      shot(0, [cellCmp(1, 0, 1)]),
      shot(1, [{ v: 'setVar', varKey: '0:i', text: '1' }]), // 사이 샷 — 저울 체류
      shot(2, [cellCmp(1, 1, 2)]),
      shot(3, [{ v: 'setVar', varKey: '0:i', text: '2' }]), // 구간 종료 — 숨김
      shot(4, [{ v: 'stdout', text: 'x' }]),
    ]
    const { scales } = compose(shots, plan, layout)
    expect(scales[0]).toBeTruthy()
    expect(scales[1]).toBeTruthy() // 사이 샷에도 자리를 안다 (카메라 추적)
    expect(scales[2]).toBeTruthy()
    expect(scales[3]).toBeNull()
    expect(scales[4]).toBeNull()
  })
})

describe('compose: 열 침범 금지', () => {
  it('넓은 포커스 상자가 있어도 대기 열은 그 오른쪽에서 시작한다', () => {
    const widePlan: StagePlan = {
      ...plan,
      objects: [
        { objectId: 1, type: 'set', life: { from: 0, to: 99 }, maxItems: 10, changeCount: 3, referencedBy: ['0:a'], slot: 0 },
        { objectId: 2, type: 'list', life: { from: 0, to: 99 }, maxItems: 4, changeCount: 3, referencedBy: ['0:b'], slot: 1 },
      ],
    }
    const wideLayout: StageLayout = {
      ...layout,
      objPos: new Map([
        [1, { x: 560, y: 70, w: 576, h: 64 }],
        [2, { x: 560, y: 182, w: 300, h: 64 }],
      ]),
    }
    const shots = [
      shot(0, [{ v: 'grow', objectId: 2, index: 0, text: '1' }]),
      shot(1, [{ v: 'grow', objectId: 1, index: 0, text: '2' }]), // 1이 포커스(넓음), 2는 대기
      shot(2, [{ v: 'setCell', objectId: 1, index: 0, text: '3' }]),
    ]
    const { comps } = compose(shots, widePlan, wideLayout)
    const focus = comps[1].get('o1')!
    const side = comps[1].get('o2')!
    expect(side.x).toBeGreaterThanOrEqual(focus.x + 576 + 40)
  })
})
