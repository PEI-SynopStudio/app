import { createSearchParams, Link, useSearchParams } from "react-router";
import { AuthLayout } from "../layouts/AuthLayout";
import { signUp } from "../lib/auth";
import { PATHS, QUERY, safeNextPath } from "../lib/paths";

// Hand the sign-up to Keycloak, which asks for name, email, password and age group and records the terms.
// A failed sign-up comes back on the login page with ?error=<code>.
// Source: backend GET /auth/register; MS3 §1.1.2, §1.4.1.
export function Signup() {
  const [params] = useSearchParams();
  const next = safeNextPath(params.get(QUERY.next));

  return (
    <AuthLayout
      title="Create account"
      subtitle="Start turning long videos into clips."
      footer={
        <>
          Already have an account?{" "}
          <Link to={{ pathname: PATHS.login, search: `?${createSearchParams({ [QUERY.next]: next })}` }}>
            Log in
          </Link>
        </>
      }
    >
      <div className="auth__form">
        <p className="auth__note">
          On the next page you'll choose your email and password and accept the{" "}
          <Link to="/terms" target="_blank" rel="noreferrer">
            Terms and Conditions
          </Link>{" "}
          and the{" "}
          <Link to="/privacy" target="_blank" rel="noreferrer">
            Privacy Policy
          </Link>
          .
        </p>
        <p className="auth__note">
          You must be at least 13 years old. If you are under 18, you need a parent or guardian’s authorization.
        </p>
        <button type="button" className="btn btn--primary btn--lg btn--block" onClick={() => signUp(next)}>
          Continue to create account
        </button>
      </div>
    </AuthLayout>
  );
}
