import { invoke } from '@tauri-apps/api/core'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { parse } from './master'

export type EditEvent = Record<string, unknown>
type Step = { text: string; event?: EditEvent }
export type SaveState = 'saved' | 'saving' | 'error'

const SAVE_AFTER_MS = 400
const PUBLISH_AFTER_MS = 10_000
const TYPING_GROUPS_MS = 800

/**
 * The master list as the window sees it: one text, one undo history, saved automatically.
 * If a sync changes the file underneath us, drags and checks are replayed on the new text. Undo can't reach back past a sync,
 * because that would quietly throw away what the sync did.
 */
export function useMaster() {
  const [text, setTextState] = useState<string | null>(null)
  const [save, setSave] = useState<SaveState>('saved')
  const [notice, setNotice] = useState('')
  const [, bump] = useState(0)
  const live = useRef('')
  const disk = useRef('')
  const past = useRef<Step[]>([])
  const future = useRef<Step[]>([])
  const pending = useRef<((md: string) => string)[] | null>([]) // null: typed in the Markdown view, so it can't be replayed
  const saveTimer = useRef(0)
  const publishTimer = useRef(0)
  const lastTyped = useRef(0)
  const saving = useRef(false)

  const show = (t: string) => {
    live.current = t
    setTextState(t)
  }
  const log = (event?: EditEvent) => {
    if (event) void invoke('log_edit', { event }).catch(() => {})
  }

  const flush = useCallback(async () => {
    window.clearTimeout(saveTimer.current)
    if (saving.current || live.current === disk.current) return
    saving.current = true
    setSave('saving')
    const text = live.current
    try {
      await invoke('write_master', { text, base: disk.current })
      disk.current = text
      pending.current = []
      setSave('saved')
      window.clearTimeout(publishTimer.current)
      publishTimer.current = window.setTimeout(() => void invoke('publish_master').catch(() => {}), PUBLISH_AFTER_MS)
    } catch (e) {
      if (String(e).includes('conflict')) {
        const fresh = await invoke<string>('read_master')
        disk.current = fresh
        if (pending.current) {
          show(pending.current.reduce((md, fn) => fn(md), fresh))
          past.current = []
          future.current = []
          setNotice('Theseus just updated the list too. Your change is kept on top of it.')
        } else {
          past.current = [{ text: live.current }]
          future.current = []
          show(fresh)
          setNotice('Theseus just updated the list while you were typing. This is its version; undo brings yours back.')
          pending.current = []
        }
        setSave('saved')
      } else {
        setSave('error')
        setNotice(`Couldn't save the list: ${e}`)
      }
    }
    saving.current = false
    bump((n) => n + 1)
    if (live.current !== disk.current) saveTimer.current = window.setTimeout(flush, SAVE_AFTER_MS)
  }, [])

  const schedule = useCallback(() => {
    setSave('saving')
    window.clearTimeout(saveTimer.current)
    saveTimer.current = window.setTimeout(flush, SAVE_AFTER_MS)
  }, [flush])

  /** A change from the list view. */
  const apply = useCallback((fn: (md: string) => string, eventOf?: EditEvent | ((before: string) => EditEvent)) => {
    const next = fn(live.current)
    if (next === live.current) return
    const event = typeof eventOf === 'function' ? eventOf(live.current) : eventOf
    past.current.push({ text: live.current, event })
    future.current = []
    pending.current?.push(fn)
    show(next)
    log(event)
    schedule()
  }, [schedule])

  /** Typing in the Markdown view. A burst of typing is one undo step. */
  const type = useCallback((next: string) => {
    const now = Date.now()
    if (now - lastTyped.current > TYPING_GROUPS_MS) past.current.push({ text: live.current })
    lastTyped.current = now
    future.current = []
    pending.current = null
    show(next)
    schedule()
  }, [schedule])

  const undo = useCallback(() => {
    const step = past.current.pop()
    if (!step) return
    future.current.push({ text: live.current, event: step.event })
    pending.current = null
    show(step.text)
    if (step.event) log({ action: 'undo', of: step.event })
    schedule()
  }, [schedule])

  const redo = useCallback(() => {
    const step = future.current.pop()
    if (!step) return
    past.current.push({ text: live.current, event: step.event })
    pending.current = null
    show(step.text)
    log(step.event)
    schedule()
  }, [schedule])

  // Load, then notice when a sync changes the file.
  useEffect(() => {
    const check = async () => {
      if (saving.current || live.current !== disk.current) return
      const fresh = await invoke<string>('read_master').catch(() => null) // a missed look just waits for the next one
      if (fresh !== null && fresh !== disk.current && !saving.current && live.current === disk.current) {
        disk.current = fresh
        past.current = []
        future.current = []
        pending.current = []
        show(fresh)
      }
    }
    void invoke<string>('read_master').then((t) => {
      disk.current = t
      show(t)
    })
    const t = window.setInterval(check, 3000)
    window.addEventListener('focus', check)
    window.addEventListener('blur', flush)
    return () => {
      window.clearInterval(t)
      window.removeEventListener('focus', check)
      window.removeEventListener('blur', flush)
    }
  }, [flush])

  // ⌘Z and ⇧⌘Z. A one-line field keeps its own undo while it's being edited.
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (!e.metaKey || e.key.toLowerCase() !== 'z') return
      if ((e.target as HTMLElement).tagName === 'INPUT') return
      e.preventDefault()
      if (e.shiftKey) redo()
      else undo()
    }
    document.addEventListener('keydown', key)
    return () => document.removeEventListener('keydown', key)
  }, [undo, redo])

  const doc = useMemo(() => (text ? parse(text) : null), [text])
  return { text, doc, save, notice, clearNotice: () => setNotice(''), apply, type, undo, redo, canUndo: past.current.length > 0, canRedo: future.current.length > 0 }
}

export type Master = ReturnType<typeof useMaster>
