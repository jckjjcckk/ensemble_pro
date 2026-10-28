import type { CapacitorConfig } from '@capacitor/cli'

// The iPad app is the built web app, bundled (webDir), never a remote server.url: App Store guideline 4.2 and
// offline both want the assets inside the binary. `npx cap sync ios` copies dist/ into ios/App/App/public.
const config: CapacitorConfig = {
  appId: 'com.jckjjcckk.folio',
  appName: 'Folio',
  webDir: 'dist',
  ios: {
    // The web app already pads itself with env(safe-area-inset-*) (viewport-fit=cover), so the webview runs edge to
    // edge and the content is not inset a second time.
    contentInset: 'never',
    scrollEnabled: false,
    backgroundColor: '#e6e8eb',
    preferredContentMode: 'mobile',
  },
  plugins: {
    SplashScreen: {
      // The launch frame is the app's light ground (--ground); the first paint applies the dark theme if chosen.
      launchAutoHide: true,
      launchShowDuration: 0,
      backgroundColor: '#e6e8eb',
      showSpinner: false,
    },
    StatusBar: {
      // Translucent over the header, like apple-mobile-web-app-status-bar-style=black-translucent in Safari.
      overlaysWebView: true,
      style: 'DEFAULT',
    },
    Keyboard: {
      // The webview itself shrinks for the keyboard; the web app's visualViewport lift (--kb) then measures 0.
      resize: 'native',
      resizeOnFullScreen: true,
    },
  },
}

export default config
