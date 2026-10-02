/**
 * [출석 페이지 전용] 연속 출석/결석 기록 → 토끼 상태(이미지·문구) 계산
 * - 학생 출석 현황 페이지(Attendance)와 출석 계단(AttendanceStairs)에서 사용
 */

import rabbitHappy from '../assets/attendance-rabbit.png'
import rabbitFire from '../assets/rabbit-fire.png'
import rabbitSleep from '../assets/rabbit-sleep.png'
import rabbitCry from '../assets/rabbit-cry.png'

/**
 * 토끼 상태
 *  - fire  : 3일 이상 연속 출석
 *  - sleep : 3일 이상 연속 결석
 *  - cry   : 7일 이상 연속 결석
 *  - happy : 그 외 (기본)
 */
export type RabbitMood = 'happy' | 'fire' | 'sleep' | 'cry'

// 기준 일수 (필요하면 여기서만 바꾸면 돼요)
export const FIRE_DAYS = 3
export const SLEEP_DAYS = 3
export const CRY_DAYS = 7

export interface AttendanceStreak {
  /** 오늘까지 연속으로 출석한 일수 (오늘 결석 상태면 0) */
  attendStreak: number
  /** 마지막 출석 이후 연속으로 출석하지 않은 일수 (오늘 출석했으면 0) */
  absentStreak: number
}

export function getRabbitMood({ attendStreak, absentStreak }: AttendanceStreak): RabbitMood {
  if (absentStreak >= CRY_DAYS) return 'cry'
  if (absentStreak >= SLEEP_DAYS) return 'sleep'
  if (attendStreak >= FIRE_DAYS) return 'fire'
  return 'happy'
}

export const MOOD_INFO: Record<
  RabbitMood,
  { image: string; title: (s: AttendanceStreak) => string; message: string }
> = {
  happy: {
    image: rabbitHappy,
    title: (s) =>
      s.attendStreak > 0 ? `${s.attendStreak}일 연속 출석 중` : '오늘도 출석해 볼까요?',
    message: `${FIRE_DAYS}일 연속으로 출석하면 토끼가 불타올라요!`,
  },
  fire: {
    image: rabbitFire,
    title: (s) => `🔥 ${s.attendStreak}일 연속 출석 중!`,
    message: '토끼가 불타오르고 있어요. 이 기세를 이어가 보세요!',
  },
  sleep: {
    image: rabbitSleep,
    title: (s) => `💤 ${s.absentStreak}일째 출석하지 않았어요`,
    message: '토끼가 잠들었어요. 출석해서 토끼를 깨워 주세요!',
  },
  cry: {
    image: rabbitCry,
    title: (s) => `😢 ${s.absentStreak}일째 출석하지 않았어요`,
    message: '토끼가 울고 있어요… 오늘 출석하면 다시 웃을 거예요.',
  },
}
