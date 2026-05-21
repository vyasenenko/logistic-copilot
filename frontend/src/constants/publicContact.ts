export const DEFAULT_CONTACT_EMAIL = "vyasenenko@logisticopilot.com";

export function getContactEmail(): string {
  return (process.env.NEXT_PUBLIC_CONTACT_EMAIL || "").trim() || DEFAULT_CONTACT_EMAIL;
}

export function bookDemoMailtoUrl(): string {
  const subject = encodeURIComponent("Logistic Copilot demo request");
  return `mailto:${getContactEmail()}?subject=${subject}`;
}
