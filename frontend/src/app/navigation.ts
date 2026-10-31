import type { RouteState } from './router'

export type NavKey = 'audit' | 'papers' | 'reports' | 'memory'

export interface NavItem {
  key: NavKey
  label: string
  href: string
  isActive: (route: RouteState) => boolean
}

export const NAV_ITEMS: NavItem[] = [
  {
    key: 'audit',
    label: '核对台',
    href: '#/',
    isActive: (route) => route.name === 'audit',
  },
  {
    key: 'papers',
    label: '论文库',
    href: '#/papers',
    isActive: (route) => route.name === 'papers',
  },
  {
    key: 'reports',
    label: '核对报告',
    href: '#/reports',
    isActive: (route) => route.name === 'reports' || route.name === 'report',
  },
  {
    key: 'memory',
    label: '项目记忆',
    href: '#/memory',
    isActive: (route) => route.name === 'memory',
  },
]
