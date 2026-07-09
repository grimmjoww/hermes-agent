import {
  AGENTS_ROUTE,
  ARTIFACTS_ROUTE,
  COMMAND_CENTER_ROUTE,
  CRON_ROUTE,
  MESSAGING_ROUTE,
  NEW_CHAT_ROUTE,
  PROFILES_ROUTE,
  SETTINGS_ROUTE,
  SKILLS_ROUTE
} from '@/app/routes'

import { DESKTOP_PLUGIN_SLOT_NAMES } from './slots'

export const DESKTOP_PLUGIN_CAPABILITIES = Object.freeze({
  host: 'desktop' as const,
  managementUi: false,
  overrideRoutes: Object.freeze([
    NEW_CHAT_ROUTE,
    SKILLS_ROUTE,
    MESSAGING_ROUTE,
    ARTIFACTS_ROUTE,
    SETTINGS_ROUTE,
    COMMAND_CENTER_ROUTE,
    CRON_ROUTE,
    PROFILES_ROUTE,
    AGENTS_ROUTE
  ]),
  slots: Object.freeze([...DESKTOP_PLUGIN_SLOT_NAMES]),
  tabs: Object.freeze({ directPath: true, hidden: true, position: true })
})

export type DesktopPluginCapabilities = typeof DESKTOP_PLUGIN_CAPABILITIES
