import { useEffect, useState } from 'react'
import { normalizeHash } from '../../app/router'

export function useHashRoute(): string {
  const [route, setRoute] = useState(() => normalizeHash(window.location.hash))
  useEffect(() => {
    const onChange = () => setRoute(normalizeHash(window.location.hash))
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  useEffect(() => {
    window.scrollTo({ top: 0 })
  }, [route])
  return route
}
