import { useRef, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import { CheckboxField, Field, TextareaField } from "../../components/Field";
import { FormSection } from "../../components/FormSection";
import { SupportingFilesField } from "../../components/SupportingFilesField";
import { VideoSourceField, type VideoSource } from "../../components/VideoSourceField";
import { usePageEnter } from "../../hooks/useMotion";
import { shake, useGSAP } from "../../lib/gsap";

const MAX_FOCUS = 1000;

const LENGTHS = [
  { value: "short", label: "Short", hint: "One paragraph with the essentials." },
  { value: "standard", label: "Standard", hint: "The key points and main takeaways." },
  { value: "detailed", label: "Detailed", hint: "Section by section, with supporting details." },
];

export function Summarize() {
  const navigate = useNavigate();
  const pageRef = useRef<HTMLDivElement>(null);
  const formRef = useRef<HTMLFormElement>(null);
  const sourceRef = useRef<HTMLDivElement>(null);
  const [source, setSource] = useState<VideoSource | null>(null);
  const [sourceError, setSourceError] = useState<string | null>(null);
  const [materials, setMaterials] = useState<File[]>([]);
  const [focus, setFocus] = useState("");

  usePageEnter(pageRef);

  const { contextSafe } = useGSAP({ scope: formRef });

  const handleSubmit = contextSafe((event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    if (!source) {
      setSourceError("Add a video file or a YouTube link to continue.");
      shake(sourceRef.current);
      return;
    }
    if (!form.checkValidity()) {
      shake(form);
      form.reportValidity();
      return;
    }
    // TODO(api): POST /summaries — video (upload or YouTube URL), `materials` and the options from FormData.
    navigate("/app");
  });

  return (
    <div className="page page--narrow" ref={pageRef}>
      <header className="page-header" data-enter>
        <div>
          <h1 className="page-title">Summarize a Video</h1>
          <p className="page-subtitle">
            Get the key points of a long video in writing — no clips needed. Want short clips instead?{" "}
            <Link to="/app/new">Create a project</Link>.
          </p>
        </div>
      </header>

      <form ref={formRef} className="form" noValidate onSubmit={handleSubmit}>
        <FormSection id="video" title="Video" description="Upload a long recording or paste a YouTube link.">
          <VideoSourceField ref={sourceRef} onChange={setSource} error={sourceError} onError={setSourceError} />
        </FormSection>

        <FormSection
          id="materials"
          title="Supporting materials"
          optional
          description="Slides, reports or notes help the AI get names, terms and context right."
        >
          <SupportingFilesField files={materials} onChange={setMaterials} />
        </FormSection>

        <FormSection id="summary" title="Summary" description="Choose how much detail you need and what matters most.">
          <div className="field">
            <p className="field__label" id="length-label">
              Length
            </p>
            <div className="choices" role="radiogroup" aria-labelledby="length-label">
              {LENGTHS.map((option) => (
                <label key={option.value} className="choice">
                  <input
                    className="sr-only"
                    type="radio"
                    name="length"
                    value={option.value}
                    defaultChecked={option.value === "standard"}
                  />
                  <span className="choice__label">{option.label}</span>
                  <span className="choice__hint">{option.hint}</span>
                </label>
              ))}
            </div>
          </div>
          <Field label="Title" name="title" maxLength={200} placeholder="Optional — defaults to the video name" />
          <TextareaField
            label="Focus"
            name="focus"
            rows={3}
            maxLength={MAX_FOCUS}
            value={focus}
            onChange={(event) => setFocus(event.target.value)}
            placeholder="Optional — e.g. decisions made, action items, questions from the audience."
            hint={`${focus.length}/${MAX_FOCUS}`}
          />
          <CheckboxField name="timestamps" defaultChecked>
            Link each key point to its moment in the video
          </CheckboxField>
        </FormSection>

        <div className="form-actions" data-enter>
          <Link to="/app" className="btn btn--ghost">
            Cancel
          </Link>
          <button type="submit" className="btn btn--primary">
            Summarize Video
          </button>
        </div>
      </form>
    </div>
  );
}