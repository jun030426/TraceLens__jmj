// 현재 3D 무대의 공용 글자 텍스처·이름표·표지판 도구.
import * as THREE from 'three'

const textureCache = new Map<string, THREE.CanvasTexture>()

/** 글자 하나짜리 캔버스 텍스처 — 길면 글자 크기를 줄여 칸 안에 맞춘다 */
export function textTexture(
  text: string,
  opts: { color: string; bg?: string; circle?: boolean; pill?: boolean; w?: number; h?: number; weight?: number },
): THREE.CanvasTexture {
  const key = JSON.stringify([text, opts])
  const hit = textureCache.get(key)
  if (hit) return hit
  const w = opts.w ?? 256
  const h = opts.h ?? 256
  const canvas = document.createElement('canvas')
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext('2d')!
  if (opts.bg) {
    ctx.fillStyle = opts.bg
    if (opts.circle) {
      ctx.beginPath()
      ctx.arc(w / 2, h / 2, Math.min(w, h) / 2 - 2, 0, Math.PI * 2)
      ctx.fill()
    } else if (opts.pill) {
      const r = h / 2 - 2
      ctx.beginPath()
      ctx.roundRect(2, 2, w - 4, h - 4, r)
      ctx.fill()
    } else ctx.fillRect(0, 0, w, h)
  }
  const family = '"Pretendard Variable", Pretendard, "Apple SD Gothic Neo", system-ui, sans-serif'
  let size = h * 0.62
  const maxW = (opts.circle ? Math.min(w, h) * 0.78 : w * 0.88)
  ctx.font = `${opts.weight ?? 800} ${size}px ${family}`
  while (ctx.measureText(text).width > maxW && size > 12) {
    size -= 4
    ctx.font = `${opts.weight ?? 800} ${size}px ${family}`
  }
  ctx.fillStyle = opts.color
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(text, w / 2, h / 2 + size * 0.04)
  const tex = new THREE.CanvasTexture(canvas)
  tex.colorSpace = THREE.SRGBColorSpace
  tex.anisotropy = 4
  if (textureCache.size > 400) textureCache.clear()
  textureCache.set(key, tex)
  return tex
}

/** 이름표 — 카메라를 늘 바라보는 스프라이트 */
export function nameSprite(text: string, color = '#3b3f52'): THREE.Sprite {
  const mat = new THREE.SpriteMaterial({
    map: textTexture(text, { color, bg: 'rgba(255,255,255,0.92)', pill: true, w: 320, h: 96, weight: 700 }),
    depthWrite: false,
    toneMapped: false,
  })
  const s = new THREE.Sprite(mat)
  s.scale.set(1.25, 0.375, 1)
  return s
}

export function setSpriteText(s: THREE.Sprite, text: string, color = '#3b3f52') {
  ;(s.material as THREE.SpriteMaterial).map = textTexture(text, { color, bg: 'rgba(255,255,255,0.92)', pill: true, w: 320, h: 96, weight: 700 })
}

/** 값이 숫자가 아닌 객체(딕셔너리·구조체 등) — 나무 팻말 대신 둥근 표지판 */
export const signTexture = (text: string) =>
  textTexture(text, { color: '#3b3f52', bg: 'rgba(255,255,255,0.95)', pill: true, w: 768, h: 96, weight: 600 })

export function makeSign(text: string): THREE.Sprite {
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: signTexture(text), depthWrite: false, toneMapped: false }))
  s.scale.set(3.2, 0.4, 1)
  return s
}
