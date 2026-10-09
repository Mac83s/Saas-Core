import { notFound } from "next/navigation";

import { panelAccess } from "./panel-navigation";
// Server-only through `server-auth`.
import { getServerCurrentOrganization } from "./server-auth";

/**
 * For the pages of a company that a platform workspace has no use for and
 * that no module gate closes — the team, the calendar, the subscription
 * (ADR-077 pkt 2 and 9). Nobody is invited there, nothing is booked and no
 * plan is bought: the API refuses each, the menu leads to none, and an
 * address typed by hand answers „Nie ma takiej strony” instead of a screen
 * whose every request is refused. A company's page goes on as it was.
 *
 * The site builder's screens are among them (ADR-079 pkt 29): the pages and
 * their editor, the menu, the site's own publication, its address and
 * domains, and the enquiries its forms bring in. No host serves a platform
 * workspace's builder site, so nothing made on them would ever be seen. The
 * API behind them stays as it is — the panel just does not lead there.
 */
export async function companyOnly(): Promise<void> {
  if (panelAccess(await getServerCurrentOrganization()).publisher) notFound();
}
