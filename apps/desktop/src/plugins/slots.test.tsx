import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { getSlotEntries, PluginSlot, registerSlot, unregisterPluginSlots } from './slots'

function FirstSlot() {
  return <div>first slot</div>
}

function ReplacementSlot() {
  return <div>replacement slot</div>
}

describe('desktop plugin slots', () => {
  afterEach(() => {
    unregisterPluginSlots('first-plugin')
    unregisterPluginSlots('second-plugin')
  })

  it('renders registered slot components and falls back when empty', () => {
    const { rerender } = render(<PluginSlot fallback={<span>empty slot</span>} name="header-left" />)

    expect(screen.getByText('empty slot')).toBeTruthy()

    registerSlot('first-plugin', 'header-left', FirstSlot)
    rerender(<PluginSlot fallback={<span>empty slot</span>} name="header-left" />)

    expect(screen.getByText('first slot')).toBeTruthy()
    expect(screen.queryByText('empty slot')).toBeNull()
  })

  it('replaces a plugin slot registration for the same plugin and slot', () => {
    registerSlot('first-plugin', 'sidebar', FirstSlot)
    registerSlot('first-plugin', 'sidebar', ReplacementSlot)

    expect(getSlotEntries('sidebar')).toHaveLength(1)

    render(<PluginSlot name="sidebar" />)

    expect(screen.getByText('replacement slot')).toBeTruthy()
    expect(screen.queryByText('first slot')).toBeNull()
  })

  it('rejects dashboard-only page slots instead of registering a silent no-op', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)

    registerSlot('first-plugin', 'analytics:top', FirstSlot)

    expect(getSlotEntries('analytics:top')).toEqual([])
    expect(warn).toHaveBeenCalledWith(expect.stringContaining('analytics:top'))
  })
})
