# Changelog

## Unreleased

### Added
- Loading spinner on action buttons (Sync, Export, login Continue) to give visual feedback during slow requests.
- Update check: on startup and page load the app checks GitHub releases and shows a banner when a newer version is available.

### Changed
- Improved session token expiry detection — distinguishes a stale stored token from a network error and redirects to login automatically.
- Added a "Clear all & re-login" button in the Sync dropdown so users can manually force a session reset without restarting the app.

## 0.1.0

- Initial release.
