import { describe, it, expect } from 'vitest'
import { preflight } from './preflight'

const codes = (issues: ReturnType<typeof preflight>) => issues.map(i => i.code)

describe('preflight — D 매트릭스', () => {
  it('input() 차단', () => expect(codes(preflight('name = input("이름: ")'))).toContain('input'))
  it('async/yield/threading 차단', () => {
    expect(codes(preflight('async def f():\n    pass'))).toContain('unsupported-model')
    expect(codes(preflight('def g():\n    yield 1'))).toContain('unsupported-model')
    expect(codes(preflight('import threading'))).toContain('unsupported-model')
  })
  it('네트워크·파일·미지원 라이브러리 차단', () => {
    expect(codes(preflight('import requests'))).toContain('external-dep')
    expect(codes(preflight('f = open("a.txt")'))).toContain('external-dep')
    expect(codes(preflight('from django.db import models'))).toContain('external-dep')
  })
  it('조각 코드(self, 클래스 없음) 경고', () =>
    expect(codes(preflight('def update(self, x):\n    self.repo.find(x)'))).toContain('fragment'))
  it('정의만 있고 호출 없음 경고', () =>
    expect(codes(preflight('def f(x):\n    return x + 1'))).toContain('no-invocation'))
  it('정상 코드는 통과', () => {
    expect(preflight('a = [1,2]\nb = a\nb.append(3)\nprint(a)')).toEqual([])
    expect(codes(preflight('class P:\n    def __init__(self):\n        self.x = 1\np = P()'))).not.toContain('fragment')
  })
})
