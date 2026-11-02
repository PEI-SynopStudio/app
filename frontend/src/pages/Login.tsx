import { useRef, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import { Field } from "../components/Field";
import { AuthLayout } from "../layouts/AuthLayout";
import { shake, useGSAP } from "../lib/gsap";

export function Login() {
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
    // TODO(auth): ligar à API quando houver especificação do login.
    navigate("/app");
  });

  return (
    <AuthLayout
      title="Log in"
      subtitle="Log in to your account to continue."
      footer={
        <>
          Don't have an account yet? <Link to="/signup">Create account</Link>
        </>
      }
    >
      <form ref={formRef} className="auth__form" noValidate onSubmit={handleSubmit}>
        <Field
          label="Email"
          name="email"
          type="email"
          autoComplete="email"
          placeholder="name@example.com"
          required
        />
        <Field label="Password" name="password" type="password" autoComplete="current-password" required />
        <button type="submit" className="btn btn--primary btn--lg btn--block">
          Log in
        </button>
      </form>
    </AuthLayout>
  );
}