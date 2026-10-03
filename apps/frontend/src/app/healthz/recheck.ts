/** How long a seen profile mismatch is answered before the backend is asked
 *  again. Its own module because a route file may export only its handlers
 *  and segment options. */
export const RECHECK_AFTER_MS = 15_000;
