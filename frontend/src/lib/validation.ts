// These helpers keep the native bubble and focus handling, with English messages.

import type { FormEvent } from "react";

type Control = HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement;

function isControl(target: unknown): target is Control {
  return (
    target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement
  );
}

export function validationMessage(control: Control): string {
  const { validity } = control;
  const type = control instanceof HTMLInputElement ? control.type : "";

  if (validity.valueMissing) {
    if (type === "checkbox") return "Check this box to continue.";
    if (type === "radio" || control instanceof HTMLSelectElement) return "Choose one of the options.";
    if (type === "file") return "Choose a file.";
    return "Fill in this field.";
  }
  if (validity.typeMismatch) {
    if (type === "email") return "Enter a valid email address, like name@example.com.";
    if (type === "url") return "Enter a valid link, starting with https://.";
    return "Enter a valid value.";
  }
  if (validity.tooShort && !(control instanceof HTMLSelectElement)) {
    return `Use at least ${control.minLength} characters (you have ${control.value.length}).`;
  }
  if (validity.tooLong && !(control instanceof HTMLSelectElement)) {
    return `Use at most ${control.maxLength} characters.`;
  }
  if (validity.patternMismatch) return control.title || "Use the requested format.";
  if (validity.rangeUnderflow && control instanceof HTMLInputElement) return `Enter ${control.min} or more.`;
  if (validity.rangeOverflow && control instanceof HTMLInputElement) return `Enter ${control.max} or less.`;
  return "Enter a valid value.";
}

/** form.reportValidity(), but with English messages whatever the browser's language. */
export function validateForm(form: HTMLFormElement): boolean {
  for (const element of Array.from(form.elements)) {
    if (!isControl(element) || !element.willValidate) continue;
    element.setCustomValidity("");
    if (!element.validity.valid) element.setCustomValidity(validationMessage(element));
  }
  return form.reportValidity();
}

/** For the form's onInput: a custom message would otherwise keep a fixed field marked invalid. */
export function clearCustomValidity(event: FormEvent<HTMLFormElement>) {
  for (const element of Array.from(event.currentTarget.elements)) {
    if (isControl(element)) element.setCustomValidity("");
  }
}