/** The sheet every librarian question and picker opens in. The implementation (`SheetMotion.tsx`, on motion/react)
 *  loads on first use, so the spring library stays out of the main bundle: the service worker precaches only
 *  chunks under 2 MiB, and OSMD already takes most of that. */
import { Suspense, lazy, type ComponentProps } from 'react'

const SheetMotion = lazy(() => import('./SheetMotion').then(m => ({ default: m.Sheet })))

export function Sheet(props: ComponentProps<typeof SheetMotion>) {
  return (
    <Suspense fallback={null}>
      <SheetMotion {...props} />
    </Suspense>
  )
}
