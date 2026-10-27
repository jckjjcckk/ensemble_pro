import { useEffect, useRef, useState } from 'react'
import { OpenSheetMusicDisplay, type IOSMDOptions } from 'opensheetmusicdisplay'

export interface ScoreViewProps {
  /** URL of a MusicXML file, e.g. a fixture path */
  src: string
  /** 1 = 100% */
  zoom?: number
  /** OSMD page format, e.g. 'A4_P', 'A4_L', 'Endless' */
  pageFormat?: string
  /** Called once per load with the live instance, for cursors, measure lookups, etc. */
  onReady?: (osmd: OpenSheetMusicDisplay) => void
  className?: string
  options?: IOSMDOptions
}

/**
 * Thin OpenSheetMusicDisplay wrapper. Renders the score into a div and
 * re-renders on zoom changes. Draws no title/composer by default so the
 * surrounding UI owns that hierarchy.
 */
export function ScoreView({ src, zoom = 1, pageFormat = 'Endless', onReady, className, options }: ScoreViewProps) {
  const ref = useRef<HTMLDivElement>(null)
  const osmdRef = useRef<OpenSheetMusicDisplay | null>(null)
  // Whether the current instance has loaded. State alone lags one render behind when src/pageFormat and zoom change together.
  const loadedRef = useRef(false)
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [error, setError] = useState<string>()

  useEffect(() => {
    if (!ref.current) return
    const osmd = new OpenSheetMusicDisplay(ref.current, {
      autoResize: true,
      backend: 'svg',
      drawTitle: false,
      drawComposer: false,
      drawSubtitle: false,
      drawLyricist: false,
      drawPartNames: true,
      drawMeasureNumbers: true,
      pageFormat,
      ...options,
    })
    osmdRef.current = osmd
    loadedRef.current = false
    let cancelled = false
    setState('loading')
    osmd.load(src)
      .then(() => {
        if (cancelled) return
        loadedRef.current = true
        osmd.zoom = zoom
        osmd.render()
        setState('ready')
        onReady?.(osmd)
      })
      .catch((e: unknown) => {
        if (cancelled) return
        setError(e instanceof Error ? e.message : String(e))
        setState('error')
      })
    return () => {
      cancelled = true
      // OSMD never removes its window resize listener; disabling autoResize makes the stale listener inert.
      osmd.AutoResizeEnabled = false
      osmd.clear()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [src, pageFormat])

  useEffect(() => {
    const osmd = osmdRef.current
    if (!osmd || state !== 'ready' || !loadedRef.current) return
    osmd.zoom = zoom
    osmd.render()
  }, [zoom, state])

  return (
    <div className={className} data-score-state={state}>
      <div ref={ref} />
      {state === 'error' && <p role="alert">Could not render score: {error}</p>}
    </div>
  )
}
