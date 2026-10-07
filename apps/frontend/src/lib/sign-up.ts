import { selfSignupTypes } from "./organization-types";

/** Where an invitation is accepted; sign-in is asked to return there. */
const INVITATION = "/invitations/accept";

/**
 * Where the sign-in screen sends somebody without an account — or null where
 * there is nowhere to send them, and then `/register` is not served either.
 *
 * A deployment none of whose organization types may be signed up for
 * (`selfSignup`, ADR-050) has no registration of its own: an account made
 * there would end at a first-run screen with no kind of organization to
 * create. Its accounts are the operator's, or an invited person's — who
 * arrives from the invitation's address (`returnTo`) and needs an account to
 * accept it, so for them the form is still there, and keeps that address.
 * Where a person may sign up, nothing changes.
 */
export function registrationHref(returnTo?: string | null): string | null {
  if (selfSignupTypes.length > 0) return "/register";
  return returnTo?.startsWith(INVITATION)
    ? `/register?next=${encodeURIComponent(returnTo)}`
    : null;
}
