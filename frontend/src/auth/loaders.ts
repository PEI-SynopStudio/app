// Route loaders that check the session before a page renders, so a signed-in page never shows to a visitor.
// Source: backend GET /auth/me; MS3 §1.1.6 (only the owner reaches their projects).

import { redirect, type LoaderFunctionArgs } from "react-router";
import { fetchCurrentUser, type User } from "../lib/auth";
import { loginPageUrl, QUERY, safeNextPath } from "../lib/paths";

/** Id of the route that holds the signed-in user; useCurrentUser reads its data. */
export const AUTH_ROUTE_ID = "auth";

/** The signed-in area: the user, or the login page with a way back here. */
export async function requireUser({ request }: LoaderFunctionArgs): Promise<User> {
  const user = await fetchCurrentUser();
  if (user) return user;
  const url = new URL(request.url);
  throw redirect(loginPageUrl(url.pathname + url.search));
}

/** The login and sign-up pages: a signed-in user goes on to next, or to the app. */
export async function redirectIfSignedIn({ request }: LoaderFunctionArgs): Promise<null> {
  let user: User | null;
  try {
    user = await fetchCurrentUser();
  } catch {
    // The session can't be checked (backend down): show the page; signing in reports the problem.
    return null;
  }
  if (!user) return null;
  throw redirect(safeNextPath(new URL(request.url).searchParams.get(QUERY.next)));
}
