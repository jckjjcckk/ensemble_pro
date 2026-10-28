# 015 iOS wrapper around the React PWA

Status: idea | Meta model: none.

## Purpose

An App Store presence for the same React app, if a store link ever matters. Not for the hackathon.

## Decisions

- PWA now: the web app is opened in Safari on iPad and installed from the deployed HTTPS URL
  (`https://folio.jckjjcckk.com`, feature 017). Capacitor later only if an App Store link matters (000).
- What a wrapper would add: a true in-app IMSLP browser with download interception (impossible in a Safari
  PWA, 002), share-to-app from Files, background audio for practice mode, MIDI over USB without the Mac.
- A native iOS developer joining the team could own a Capacitor shell; nobody has answered the recruiting
  post yet.
- Xcode is installed on the Mac.

## Next steps

None until after Nov 4.
