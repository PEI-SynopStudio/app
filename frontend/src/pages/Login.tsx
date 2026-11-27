import { createSearchParams, Link, useSearchParams } from "react-router";
import { AuthLayout } from "../layouts/AuthLayout";
import { loginErrorMessage, SESSION_EXPIRED_MESSAGE, signIn } from "../lib/auth";
import { isExpiredLogin, PATHS, QUERY, safeNextPath } from "../lib/paths";

// Hand the sign-in to Keycloak; the backend brings the browser back to next, or here with ?error=<code>.
// Source: backend GET /auth/login and /auth/callback; MS3 §1.1.6.
export function Login() {
  const [params] = useSearchParams();
  const next = safeNextPath(params.get(QUERY.next));
  const error = loginErrorMessage(params.get(QUERY.error));
  const expired = !error && isExpiredLogin(params);

  return (
    <AuthLayout
      title="Log in"
      subtitle="Log in to your account to continue."
      footer={
        <>
          Don't have an account yet?{" "}
          <Link to={{ pathname: PATHS.signup, search: `?${createSearchParams({ [QUERY.next]: next })}` }}>
            Create account
          </Link>
        </>
      }
    >
      <div className="auth__form">
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        {expired && (
          <p className="form-error" role="status">
            {SESSION_EXPIRED_MESSAGE}
          </p>
        )}
        <button type="button" className="btn btn--primary btn--lg btn--block" onClick={() => signIn(next)}>
          Continue to log in
        </button>
        <p className="auth__note">You'll enter your email and password on the SynopStudio sign-in page.</p>
      </div>
    </AuthLayout>
  );
}
