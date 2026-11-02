import { useRef, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import { CheckboxField, Field } from "../components/Field";
import { PRIVACY } from "../data/privacy";
import { TERMS } from "../data/terms";
import { AuthLayout } from "../layouts/AuthLayout";
import { shake, useGSAP } from "../lib/gsap";

export function Signup() {
  const navigate = useNavigate();
  const formRef = useRef<HTMLFormElement>(null);
  const { contextSafe } = useGSAP({ scope: formRef });

  const handleSubmit = contextSafe((event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    if (!form.checkValidity()) {
      shake(form);
      form.reportValidity();
      return;
    }
    // TODO(auth): connect to the API once the sign-up spec exists (send termsVersion and privacyVersion).
    navigate("/app");
  });

  return (
    <AuthLayout
      title="Create account"
      subtitle="Start turning long videos into clips."
      footer={
        <>
          Already have an account? <Link to="/login">Log in</Link>
        </>
      }
    >
      <form ref={formRef} className="auth__form" noValidate onSubmit={handleSubmit}>
        <Field label="Name" name="name" autoComplete="name" required />
        <Field
          label="Email"
          name="email"
          type="email"
          autoComplete="email"
          placeholder="name@example.com"
          required
        />
        <Field
          label="Password"
          name="password"
          type="password"
          autoComplete="new-password"
          minLength={8}
          hint="At least 8 characters."
          required
        />
        <CheckboxField name="acceptTerms" required>
          I agree to the{" "}
          <Link to="/terms" target="_blank" rel="noreferrer">
            Terms and Conditions
          </Link>{" "}
          and confirm I am at least 13 years old (with a parent or guardian’s authorization if under 18).
        </CheckboxField>
        <CheckboxField name="acceptPrivacy" required>
          I have read the{" "}
          <Link to="/privacy" target="_blank" rel="noreferrer">
            Privacy Policy
          </Link>{" "}
          and understand how my personal data is processed.
        </CheckboxField>
        <input type="hidden" name="termsVersion" value={TERMS.version} />
        <input type="hidden" name="privacyVersion" value={PRIVACY.version} />
        <button type="submit" className="btn btn--primary btn--lg btn--block">
          Create account
        </button>
      </form>
    </AuthLayout>
  );
}