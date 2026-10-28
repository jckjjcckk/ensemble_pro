import { Capacitor } from '@capacitor/core'

/**
 * The iPad app is the web app inside a Capacitor shell. Everything here is a no-op or a web fallback in Safari, so
 * the hosted site keeps working unchanged; the plugins load only when the app runs natively.
 */
export const isNative = Capacitor.isNativePlatform()

/** A page photographed with the device camera (native) or picked with the browser's file chooser (web). */
export interface CapturedPage { file: File; url: string }

async function fileFromUri(webPath: string, name: string): Promise<File> {
  const blob = await (await fetch(webPath)).blob()
  return new File([blob], name, { type: blob.type || 'image/jpeg' })
}

/** Open the camera and return the photo, or null when the musician cancelled. Web: an image file chooser (the iPad
 *  offers "Take Photo" there too), several pages at once. */
export async function capturePages(): Promise<CapturedPage[]> {
  if (isNative) {
    const { Camera, CameraResultType, CameraSource } = await import('@capacitor/camera')
    try {
      const photo = await Camera.getPhoto({ source: CameraSource.Camera, resultType: CameraResultType.Uri, quality: 85, correctOrientation: true, saveToGallery: false })
      if (!photo.webPath) return []
      const file = await fileFromUri(photo.webPath, `page-${Date.now()}.${photo.format || 'jpeg'}`)
      return [{ file, url: photo.webPath }]
    } catch {
      return [] // cancelled, or the camera permission refused: nothing to add
    }
  }
  return new Promise(resolve => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = 'image/*'
    input.multiple = true
    input.setAttribute('capture', 'environment')
    input.className = 'sr-only'
    input.onchange = () => {
      const files = Array.from(input.files ?? [])
      input.remove()
      resolve(files.map(file => ({ file, url: URL.createObjectURL(file) })))
    }
    input.oncancel = () => { input.remove(); resolve([]) }
    document.body.append(input)
    input.click()
  })
}

/** Hand a file to the musician. Native: the share sheet (Save to Files, AirDrop, Mail). Web: a download, which Safari
 *  on the iPad offers to save to Files. */
export async function deliverFile(blob: Blob, filename: string): Promise<void> {
  if (isNative) {
    const [{ Filesystem, Directory }, { Share }] = await Promise.all([import('@capacitor/filesystem'), import('@capacitor/share')])
    const data = await new Promise<string>((resolve, reject) => {
      const r = new FileReader()
      r.onload = () => resolve((r.result as string).split(',')[1] ?? '')
      r.onerror = () => reject(r.error)
      r.readAsDataURL(blob)
    })
    const written = await Filesystem.writeFile({ path: filename, data, directory: Directory.Cache })
    try {
      await Share.share({ title: filename, url: written.uri })
    } catch {
      /* the sheet was dismissed */
    }
    return
  }
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.rel = 'noopener'
  document.body.append(a)
  a.click()
  a.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 30_000)
}

/** The status bar's text follows the theme: light text over the dark ground, dark text over the light one. */
export async function syncStatusBar(dark: boolean): Promise<void> {
  if (!isNative) return
  const { StatusBar, Style } = await import('@capacitor/status-bar')
  await StatusBar.setStyle({ style: dark ? Style.Dark : Style.Light }).catch(() => undefined)
}

/** A light tap under the finger, where the web has nothing. */
export async function tap(): Promise<void> {
  if (!isNative) return
  const { Haptics, ImpactStyle } = await import('@capacitor/haptics')
  await Haptics.impact({ style: ImpactStyle.Light }).catch(() => undefined)
}
