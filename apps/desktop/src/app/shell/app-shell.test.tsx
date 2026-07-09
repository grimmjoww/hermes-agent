import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it } from 'vitest'

import { registerSlot, unregisterPluginSlots } from '@/plugins/slots'

import { AppShell } from './app-shell'

function HeaderBanner() {
  return <div>plugin header banner</div>
}

function HeaderLeft() {
  return <div>plugin header left</div>
}

function HeaderRight() {
  return <div>plugin header right</div>
}

function Overlay() {
  return <div>plugin overlay</div>
}

function FooterLeft() {
  return <div>plugin footer left</div>
}

function FooterRight() {
  return <div>plugin footer right</div>
}

describe('AppShell plugin slots', () => {
  afterEach(() => {
    cleanup()
    unregisterPluginSlots('shell-plugin')
  })

  it('mounts dashboard-compatible shell slots in the desktop chrome', () => {
    registerSlot('shell-plugin', 'header-banner', HeaderBanner)
    registerSlot('shell-plugin', 'header-left', HeaderLeft)
    registerSlot('shell-plugin', 'header-right', HeaderRight)
    registerSlot('shell-plugin', 'overlay', Overlay)
    registerSlot('shell-plugin', 'footer-left', FooterLeft)
    registerSlot('shell-plugin', 'footer-right', FooterRight)

    render(
      <MemoryRouter>
        <AppShell onOpenSettings={() => undefined}>
          <div>desktop content</div>
        </AppShell>
      </MemoryRouter>
    )

    const headerBanner = screen.getByText('plugin header banner')

    expect(headerBanner).toBeTruthy()
    expect(headerBanner.parentElement?.classList.contains('pt-(--titlebar-height)')).toBe(true)
    expect(screen.getByText('plugin header left')).toBeTruthy()
    expect(screen.getByText('plugin header right')).toBeTruthy()
    expect(screen.getByText('plugin overlay')).toBeTruthy()
    expect(screen.getByText('plugin footer left')).toBeTruthy()
    expect(screen.getByText('plugin footer right')).toBeTruthy()
  })
})
