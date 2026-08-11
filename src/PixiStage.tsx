import { useEffect, useMemo, useRef, useState } from 'react'
import { Application, Container, Graphics, Text } from 'pixi.js'
import { GlowFilter } from 'pixi-filters'
import gsap from 'gsap'
import type { TraceArrayElement, TraceFrame, TracePointer } from './tracing'

type BarNode = {
  group: Container
  glow: Graphics
  body: Graphics
  valueText: Text
  indexText: Text
  pointerText: Text
}

type PixiStageProps = {
  frame?: TraceFrame
}

const emptyElements: TraceArrayElement[] = []

const stateColor: Record<TraceArrayElement['state'], number> = {
  default: 0x38d7e8,
  active_neon: 0xff4fd8,
  swapped: 0xffd166,
  settled: 0x68ff7a,
  muted: 0x556070,
  found: 0x68ff7a,
  boundary: 0xffd166,
  discarded: 0x394150,
  candidate: 0x38d7e8,
}

const glowFor = (state: TraceArrayElement['state']) => {
  if (state === 'active_neon') {
    return new GlowFilter({
      color: 0xff4fd8,
      distance: 18,
      outerStrength: 4,
      innerStrength: 0.8,
      quality: 0.35,
    })
  }

  if (state === 'settled') {
    return new GlowFilter({
      color: 0x68ff7a,
      distance: 10,
      outerStrength: 1.4,
      innerStrength: 0.35,
      quality: 0.25,
    })
  }

  if (state === 'found') {
    return new GlowFilter({
      color: 0x68ff7a,
      distance: 20,
      outerStrength: 4.2,
      innerStrength: 0.8,
      quality: 0.35,
    })
  }

  if (state === 'boundary') {
    return new GlowFilter({
      color: 0xffd166,
      distance: 12,
      outerStrength: 1.7,
      innerStrength: 0.35,
      quality: 0.25,
    })
  }

  return null
}

const createText = (
  fontSize: number,
  fill: string,
  weight: '400' | '600' | '700' = '700',
) =>
  new Text({
    text: '',
    style: {
      fill,
      fontFamily: 'Inter, Segoe UI, system-ui, sans-serif',
      fontSize,
      fontWeight: weight,
    },
  })

const drawGrid = (grid: Graphics, width: number, height: number) => {
  grid.clear()
  grid.rect(0, 0, width, height)
  grid.fill({ color: 0x080b10, alpha: 1 })

  const horizontalLines = 5
  const verticalStep = 68

  for (let i = 1; i < horizontalLines; i += 1) {
    const y = (height / horizontalLines) * i
    grid.moveTo(24, y)
    grid.lineTo(width - 24, y)
    grid.stroke({ color: 0x25303a, alpha: 0.35, width: 1 })
  }

  for (let x = 24; x < width; x += verticalStep) {
    grid.moveTo(x, 24)
    grid.lineTo(x, height - 24)
    grid.stroke({ color: 0x1a232c, alpha: 0.26, width: 1 })
  }
}

const drawNode = ({
  node,
  element,
  barWidth,
  barHeight,
  maxBarHeight,
  pointerLabel = '',
}: {
  node: BarNode
  element: TraceArrayElement
  barWidth: number
  barHeight: number
  maxBarHeight: number
  pointerLabel?: string
}) => {
  const color = stateColor[element.state]
  const glow = glowFor(element.state)
  const radius = Math.min(8, barWidth / 3)

  node.body.clear()
  node.body.roundRect(-barWidth / 2, -barHeight, barWidth, barHeight, radius)
  node.body.fill({ color, alpha: 0.92 })
  node.body.stroke({
    color: element.state === 'default' ? 0x86f6ff : 0xffffff,
    alpha: element.state === 'default' ? 0.22 : 0.45,
    width: 1,
  })

  node.glow.clear()
  node.glow.filters = glow ? [glow] : []

  if (glow) {
    node.glow.roundRect(
      -barWidth / 2 - 3,
      -barHeight - 3,
      barWidth + 6,
      barHeight + 6,
      radius + 2,
    )
    node.glow.fill({ color, alpha: 0.5 })
  }

  node.valueText.text = String(element.value)
  node.valueText.anchor.set(0.5, 1)
  node.valueText.y = Math.min(-barHeight - 8, -maxBarHeight - 12)

  node.indexText.text = String(element.index)
  node.indexText.anchor.set(0.5, 0)
  node.indexText.y = 10

  node.pointerText.text = pointerLabel
  node.pointerText.anchor.set(0.5, 1)
  node.pointerText.y = Math.min(-barHeight - 28, -maxBarHeight - 32)
  node.pointerText.alpha = pointerLabel ? 1 : 0
}

const drawCellNode = ({
  node,
  element,
  cellSize,
  pointerLabel = '',
}: {
  node: BarNode
  element: TraceArrayElement
  cellSize: number
  pointerLabel?: string
}) => {
  const color = stateColor[element.state]
  const glow = glowFor(element.state)
  const alpha =
    element.state === 'discarded' || element.state === 'muted' ? 0.34 : 0.92

  node.body.clear()
  node.body.roundRect(-cellSize / 2, -cellSize / 2, cellSize, cellSize, 8)
  node.body.fill({ color, alpha })
  node.body.stroke({
    color: element.state === 'candidate' ? 0x86f6ff : 0xffffff,
    alpha: element.state === 'candidate' ? 0.28 : 0.42,
    width: 1,
  })

  node.glow.clear()
  node.glow.filters = glow ? [glow] : []

  if (glow) {
    node.glow.roundRect(
      -cellSize / 2 - 4,
      -cellSize / 2 - 4,
      cellSize + 8,
      cellSize + 8,
      10,
    )
    node.glow.fill({ color, alpha: 0.42 })
  }

  node.valueText.text = String(element.value)
  node.valueText.anchor.set(0.5, 0.5)
  node.valueText.y = -4

  node.indexText.text = String(element.index)
  node.indexText.anchor.set(0.5, 0)
  node.indexText.y = cellSize / 2 + 9

  node.pointerText.text = pointerLabel
  node.pointerText.anchor.set(0.5, 1)
  node.pointerText.y = -cellSize / 2 - 10
  node.pointerText.alpha = pointerLabel ? 1 : 0
}

const pointerLabelFor = (pointers: TracePointer[], index: number) =>
  pointers
    .filter((pointer) => pointer.index === index)
    .map((pointer) => pointer.name)
    .join('/')

export default function PixiStage({ frame }: PixiStageProps) {
  const [ready, setReady] = useState(false)
  const hostRef = useRef<HTMLDivElement | null>(null)
  const appRef = useRef<Application | null>(null)
  const gridRef = useRef<Graphics | null>(null)
  const layerRef = useRef<Container | null>(null)
  const nodesRef = useRef<Map<string, BarNode>>(new Map())

  const structure = useMemo(
    () => frame?.structures.find((item) => item.kind === 'array'),
    [frame],
  )
  const elements = structure?.elements ?? emptyElements

  useEffect(() => {
    const host = hostRef.current

    if (!host) {
      return
    }

    let disposed = false
    let initialized = false
    let canvas: HTMLCanvasElement | null = null
    const app = new Application()
    const nodes = nodesRef.current

    const setup = async () => {
      await app.init({
        antialias: true,
        autoDensity: true,
        backgroundAlpha: 0,
        resolution: window.devicePixelRatio || 1,
        resizeTo: host,
      })

      initialized = true
      canvas = app.canvas

      if (disposed) {
        app.destroy()
        return
      }

      canvas.className = 'pixi-canvas'
      host.appendChild(canvas)

      const grid = new Graphics()
      const layer = new Container()

      app.stage.addChild(grid)
      app.stage.addChild(layer)

      appRef.current = app
      gridRef.current = grid
      layerRef.current = layer
      setReady(true)
    }

    void setup()

    return () => {
      disposed = true
      nodes.forEach((node) => {
        gsap.killTweensOf(node.group)
        gsap.killTweensOf(node.group.scale)
      })
      nodes.clear()

      if (canvas?.parentNode) {
        canvas.remove()
      }

      if (initialized) {
        app.destroy()
      }
    }
  }, [])

  useEffect(() => {
    const host = hostRef.current
    const app = appRef.current
    const grid = gridRef.current
    const layer = layerRef.current

    if (!ready || !host || !app || !grid || !layer || elements.length === 0) {
      return
    }

    const width = host.clientWidth
    const height = host.clientHeight
    const view = structure?.view ?? 'bar_sort'
    const pointers = structure?.pointers ?? []
    const baseY = Math.max(height - 64, 160)
    const maxBarHeight = Math.max(height - 172, 86)
    const maxValue = Math.max(...elements.map((element) => Math.abs(element.value)), 1)

    drawGrid(grid, width, height)

    const nextIds = new Set(elements.map((element) => element.itemId))

    nodesRef.current.forEach((node, itemId) => {
      if (!nextIds.has(itemId)) {
        gsap.killTweensOf(node.group)
        layer.removeChild(node.group)
        node.group.destroy({ children: true })
        nodesRef.current.delete(itemId)
      }
    })

    elements.forEach((element) => {
      let node = nodesRef.current.get(element.itemId)

      if (!node) {
        const group = new Container()
        const glow = new Graphics()
        const body = new Graphics()
        const valueText = createText(13, '#f8fafc')
        const indexText = createText(11, '#9aa7b8', '600')
        const pointerText = createText(11, '#f8fbff', '700')

        group.addChild(glow)
        group.addChild(body)
        group.addChild(valueText)
        group.addChild(indexText)
        group.addChild(pointerText)
        layer.addChild(group)

        node = { group, glow, body, valueText, indexText, pointerText }
        nodesRef.current.set(element.itemId, node)
      }

      if (view === 'bar_sort') {
        const step = Math.max((width - 88) / Math.max(elements.length, 1), 34)
        const barWidth = Math.min(44, Math.max(18, step * 0.58))
        const startX = width / 2 - ((elements.length - 1) * step) / 2
        const barHeight = Math.max(18, (Math.abs(element.value) / maxValue) * maxBarHeight)
        const targetX = startX + element.index * step

        drawNode({
          node,
          element,
          barWidth,
          barHeight,
          maxBarHeight,
          pointerLabel: pointerLabelFor(pointers, element.index),
        })

        if (node.group.y !== baseY) {
          node.group.y = baseY
        }

        if (node.group.x === 0) {
          node.group.x = targetX
        }

        gsap.to(node.group, {
          x: targetX,
          duration: frame?.event.name === 'array_swap' ? 0.72 : 0.36,
          ease: frame?.event.name === 'array_swap' ? 'elastic.out(1, 0.72)' : 'power3.out',
          overwrite: true,
        })
      } else {
        const step = Math.min(80, Math.max(46, (width - 104) / Math.max(elements.length, 1)))
        const cellSize = Math.min(62, Math.max(38, step * 0.72))
        const startX = width / 2 - ((elements.length - 1) * step) / 2
        const targetX = startX + element.index * step
        const targetY = Math.max(136, Math.min(height - 112, height * 0.5))

        drawCellNode({
          node,
          element,
          cellSize,
          pointerLabel: pointerLabelFor(pointers, element.index),
        })

        if (node.group.y !== targetY) {
          node.group.y = targetY
        }

        if (node.group.x === 0) {
          node.group.x = targetX
        }

        gsap.to(node.group, {
          x: targetX,
          duration: 0.38,
          ease: 'back.out(1.7)',
          overwrite: true,
        })
      }

      if (
        element.state === 'active_neon' ||
        element.state === 'found' ||
        element.state === 'boundary'
      ) {
        gsap.fromTo(
          node.group.scale,
          { x: 1.05, y: 1.05 },
          {
            x: 1,
            y: 1,
            duration: 0.36,
            ease: 'back.out(2)',
            overwrite: true,
          },
        )
      }
    })
  }, [elements, frame?.event.name, ready, structure])

  return (
    <div className="stage-shell" ref={hostRef}>
      <div className="stage-readout">
        <span>{frame?.event.label ?? 'idle'}</span>
        <strong>{frame ? `line ${frame.currentLine}` : 'line -'}</strong>
      </div>
    </div>
  )
}
