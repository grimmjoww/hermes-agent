import type { ComponentType, ReactNode } from 'react'

import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  exposePluginSDK,
  getPluginComponent,
  getPluginLoadError,
  onPluginRegistered,
  setPluginLoadError
} from './registry'

function TestPlugin() {
  return null
}

function resetPluginGlobals() {
  delete (window as unknown as { __HERMES_PLUGINS__?: unknown }).__HERMES_PLUGINS__
  delete (window as unknown as { __HERMES_PLUGIN_SDK__?: unknown }).__HERMES_PLUGIN_SDK__
}

describe('desktop plugin registry', () => {
  afterEach(() => {
    resetPluginGlobals()
    document.body.innerHTML = ''
  })

  it('exposes registry globals that plugins use to register components', () => {
    const listener = vi.fn()
    const unsubscribe = onPluginRegistered(listener)

    exposePluginSDK()

    window.__HERMES_PLUGINS__!.register('kanban', TestPlugin)

    expect(getPluginComponent('kanban')).toBe(TestPlugin)
    expect(getPluginLoadError('kanban')).toBeUndefined()
    expect(listener).toHaveBeenCalledTimes(1)

    unsubscribe()
  })

  it('notifies subscribers when a plugin load error is recorded', () => {
    const listener = vi.fn()
    const unsubscribe = onPluginRegistered(listener)

    setPluginLoadError('broken-plugin', 'LOAD_FAILED')

    expect(getPluginLoadError('broken-plugin')).toBe('LOAD_FAILED')
    expect(listener).toHaveBeenCalledTimes(1)

    unsubscribe()
  })

  it('replaces a component when a plugin registers again', () => {
    function ReplacementPlugin() {
      return null
    }

    exposePluginSDK()

    window.__HERMES_PLUGINS__!.register('kanban', TestPlugin)
    window.__HERMES_PLUGINS__!.register('kanban', ReplacementPlugin)

    expect(getPluginComponent('kanban')).toBe(ReplacementPlugin)
  })

  it('exposes the dashboard plugin SDK surface used by bundled plugins', () => {
    exposePluginSDK()

    expect(window.__HERMES_PLUGIN_SDK__!.components.Card).toBeTypeOf('function')
    expect(window.__HERMES_PLUGIN_SDK__!.components.CardContent).toBeTypeOf('function')
    expect(window.__HERMES_PLUGIN_SDK__!.components.Label).toBeTypeOf('function')
    expect(window.__HERMES_PLUGIN_SDK__!.components.PluginSlot).toBeTypeOf('function')
    expect(window.__HERMES_PLUGIN_SDK__!.components.SelectOption).toBeTypeOf('function')
    expect(window.__HERMES_PLUGIN_SDK__!.authedFetch).toBeTypeOf('function')
    expect(window.__HERMES_PLUGIN_SDK__!.buildWsAuthParam).toBeTypeOf('function')
    expect(window.__HERMES_PLUGIN_SDK__!.buildWsUrl).toBeTypeOf('function')
    expect(window.__HERMES_PLUGIN_SDK__!.useI18n).toBeTypeOf('function')
    expect(window.__HERMES_PLUGIN_SDK__!.utils.timeAgo).toBeTypeOf('function')
    expect(window.__HERMES_PLUGIN_SDK__!.utils.isoTimeAgo).toBeTypeOf('function')
    expect(window.__HERMES_PLUGINS__!.registerSlot).toBeTypeOf('function')
  })

  it('exposes immutable desktop host capabilities for cross-host plugins', () => {
    exposePluginSDK()

    const capabilities = window.__HERMES_PLUGIN_SDK__!.capabilities

    expect(capabilities).toMatchObject({
      host: 'desktop',
      managementUi: false,
      tabs: { directPath: true, hidden: true, position: true }
    })
    expect(capabilities.overrideRoutes).toEqual([
      '/',
      '/skills',
      '/messaging',
      '/artifacts',
      '/settings',
      '/command-center',
      '/cron',
      '/profiles',
      '/agents'
    ])
    expect(capabilities.slots).toContain('header-banner')
    expect(Object.isFrozen(capabilities)).toBe(true)
    expect(Object.isFrozen(capabilities.overrideRoutes)).toBe(true)
    expect(Object.isFrozen(capabilities.slots)).toBe(true)
  })

  it('supports the web plugin Select/SelectOption contract', async () => {
    exposePluginSDK()

    const { Select, SelectOption } = window.__HERMES_PLUGIN_SDK__!.components as unknown as {
      Select: ComponentType<{ children?: ReactNode; placeholder?: string; value?: string }>
      SelectOption: ComponentType<{ children?: ReactNode; value: string }>
    }

    render(
      <Select placeholder="Pick status" value="todo">
        <SelectOption value="todo">To do</SelectOption>
        <SelectOption value="done">Done</SelectOption>
      </Select>
    )

    fireEvent.click(screen.getByRole('combobox'))

    expect(await screen.findByRole('option', { name: /Done/ })).toBeTruthy()
  })
})
