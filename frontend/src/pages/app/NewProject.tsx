import { useRef, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import { CaptionOptions } from "../../components/CaptionOptions";
import { Field, TextareaField } from "../../components/Field";
import { FormatPicker } from "../../components/FormatPicker";
import { FormSection } from "../../components/FormSection";
import { IconArrowLeft } from "../../components/Icons";
import { SupportingFilesField } from "../../components/SupportingFilesField";
import { VideoSourceField, type VideoSource } from "../../components/VideoSourceField";
import { DEFAULT_CAPTIONS, type AspectRatio, type CaptionSettings } from "../../data/options";
import { usePageEnter } from "../../hooks/useMotion";
import { shake, useGSAP } from "../../lib/gsap";

const MAX_DESCRIPTION = 2000;

export function NewProject() {
  const navigate = useNavigate();
  const pageRef = useRef<HTMLDivElement>(null);
  const formRef = useRef<HTMLFormElement>(null);
  const sourceRef = useRef<HTMLDivElement>(null);
  const [source, setSource] = useState<VideoSource | null>(null);
  const [sourceError, setSourceError] = useState<string | null>(null);
  const [materials, setMaterials] = useState<File[]>([]);
  const [description, setDescription] = useState("");
  const [format, setFormat] = useState<AspectRatio>("9:16");
  const [captions, setCaptions] = useState<CaptionSettings | null>(DEFAULT_CAPTIONS);

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
    // TODO(api): POST /projects — video (upload or YouTube URL), `materials`, `format` and `captions`.
    navigate("/app");
  });

  return (
    <div className="page page--narrow" ref={pageRef}>
      <header className="page-header" data-enter>
        <div>
          <Link to="/app" className="back-link">
            <IconArrowLeft /> Projects
          </Link>
          <h1 className="page-title">New Project</h1>
          <p className="page-subtitle">
            Add a long video and we'll generate short clips from it. Only need a summary?{" "}
            <Link to="/app/summarize">Summarize it instead</Link>.
          </p>
        </div>
      </header>

      <form ref={formRef} className="form" noValidate onSubmit={handleSubmit}>
        <FormSection id="video" title="Video" description="Upload a long recording or paste a YouTube link.">
          <VideoSourceField ref={sourceRef} onChange={setSource} error={sourceError} onError={setSourceError} />
        </FormSection>

        <FormSection id="details" title="Details">
          <Field label="Title" name="title" required maxLength={200} placeholder="Ex.: Interview — Episode 13" />
          <TextareaField
            label="Description"
            name="description"
            rows={4}
            maxLength={MAX_DESCRIPTION}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="Optional — context that helps choose the best moments."
            hint={`${description.length}/${MAX_DESCRIPTION}`}
          />
        </FormSection>

        <FormSection id="format" title="Format" description="How the clips will be framed. You can change it per clip later.">
          <FormatPicker value={format} onChange={setFormat} />
        </FormSection>

        <FormSection id="subtitles" title="Subtitles" description="Applied to every clip. You can change them per clip later.">
          <CaptionOptions value={captions} onChange={setCaptions} />
        </FormSection>

        <FormSection
          id="materials"
          title="Supporting materials"
          optional
          description="Slides, reports or scripts help the AI understand the context and pick better moments."
        >
          <SupportingFilesField files={materials} onChange={setMaterials} />
        </FormSection>

        <div className="form-actions" data-enter>
          <Link to="/app" className="btn btn--ghost">
            Cancel
          </Link>
          <button type="submit" className="btn btn--primary">
            Create Project
          </button>
        </div>
      </form>
    </div>
  );
}