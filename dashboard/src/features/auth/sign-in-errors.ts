/** Fixed copy for every /login?error= code (spec 2026-10-19, section 2). */
export const SIGN_IN_ERRORS: Record<string, string> = {
  unverified_email: "Your provider has not verified this email address.",
  not_allowed: "This account is not allowed to sign in to this workspace.",
  provider_error: "Sign-in did not complete. Try again.",
  not_configured: "Sign-in is not configured on this server.",
  too_many_codes: "Too many codes were sent today. Try again tomorrow.",
  too_soon: "A code was sent less than a minute ago. Check your email, or wait a minute.",
  code_not_sent: "The sign-in code could not be sent. Try again.",
  unavailable: "Sign-in is unavailable right now. Try again shortly.",
};
