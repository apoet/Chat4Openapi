export interface DestructiveConfirmationOptions {
  title: string
  message: string
  subject?: string
  warning: string
  confirmLabel: string
  cancelLabel: string
}

let confirmationSequence = 0

export function confirmDestructiveAction(
  options: DestructiveConfirmationOptions,
): Promise<boolean> {
  if (typeof document === 'undefined') return Promise.resolve(false)

  return new Promise((resolve) => {
    const sequence = ++confirmationSequence
    const titleId = `destructive-confirmation-title-${sequence}`
    const descriptionId = `destructive-confirmation-description-${sequence}`
    const previousFocus = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null
    const dialog = document.createElement('dialog')
    dialog.className = 'confirmation-dialog destructive-confirmation-dialog'
    dialog.setAttribute('aria-labelledby', titleId)
    dialog.setAttribute('aria-describedby', descriptionId)

    const icon = document.createElement('span')
    icon.className = 'confirmation-icon'
    icon.setAttribute('aria-hidden', 'true')
    icon.textContent = '!'

    const copy = document.createElement('div')
    copy.className = 'confirmation-copy'
    const title = document.createElement('h2')
    title.id = titleId
    title.textContent = options.title
    const message = document.createElement('p')
    message.id = descriptionId
    message.textContent = options.message
    copy.append(title, message)

    if (options.subject) {
      const subject = document.createElement('strong')
      subject.className = 'confirmation-subject'
      subject.textContent = options.subject
      copy.append(subject)
    }

    const warning = document.createElement('p')
    warning.className = 'confirmation-warning'
    warning.textContent = options.warning
    copy.append(warning)

    const header = document.createElement('div')
    header.className = 'confirmation-header'
    header.append(icon, copy)

    const cancelButton = document.createElement('button')
    cancelButton.type = 'button'
    cancelButton.className = 'secondary-action'
    cancelButton.textContent = options.cancelLabel
    const confirmButton = document.createElement('button')
    confirmButton.type = 'button'
    confirmButton.className = 'danger-action confirmation-danger-action'
    confirmButton.textContent = options.confirmLabel
    const actions = document.createElement('div')
    actions.className = 'confirmation-actions'
    actions.append(cancelButton, confirmButton)
    dialog.append(header, actions)

    let settled = false
    const finish = (confirmed: boolean): void => {
      if (settled) return
      settled = true
      if (dialog.open && typeof dialog.close === 'function') dialog.close()
      dialog.remove()
      previousFocus?.focus()
      resolve(confirmed)
    }

    cancelButton.addEventListener('click', () => finish(false))
    confirmButton.addEventListener('click', () => finish(true))
    dialog.addEventListener('cancel', (event) => {
      event.preventDefault()
      finish(false)
    })
    dialog.addEventListener('click', (event) => {
      if (event.target === dialog) finish(false)
    })

    document.body.append(dialog)
    if (typeof dialog.showModal === 'function') dialog.showModal()
    else dialog.setAttribute('open', '')
    cancelButton.focus()
  })
}
