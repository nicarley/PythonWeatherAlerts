# PyWeatherAlert iOS

This folder contains a native SwiftUI iPad app version of PyWeatherAlert.

## What is included

- Saved locations with local persistence
- NWS alert loading for the selected location
- 8-period hourly forecast and 10-period daily forecast
- Embedded NWS forecast page
- Embedded radar/web source page
- iPad-friendly split view layout

## What is different from the desktop app

This iOS build is a native rewrite. It does not try to run the PySide desktop UI on iPad.

The following desktop-only features are not included in this first pass:

- System tray behavior
- Desktop-style dialogs and menus
- Local text-to-speech alerts
- PDF/CSV export
- Webhook delivery dashboards
- Full per-location rule editing

## Open in Xcode

1. On a Mac, open `PyWeatherAlertIOS.xcodeproj` in Xcode.
2. Choose an iPad simulator or an iPad device target.
3. Build and run.

XcodeGen is no longer required for the current checked-in project, though `project.yml` is still included as a reference scaffold.

## Notes

- The app uses `api.weather.gov` directly with a custom user agent.
- Location inputs support `lat,lon`, a 3 or 4 letter station ID, ZIP, and normal address/city text through iOS geocoding.
- Saved settings are stored locally in the app's documents directory.
