import { StatusLight } from '@adobe/react-spectrum';
import Document from '@spectrum-icons/workflow/Document';
import FileCSV from '@spectrum-icons/workflow/FileCSV';
import FileJson from '@spectrum-icons/workflow/FileJson';
import FilePDF from '@spectrum-icons/workflow/FilePDF';
import FileTxt from '@spectrum-icons/workflow/FileTxt';
import FileWord from '@spectrum-icons/workflow/FileWord';
import { formatOf, type Format, type Light } from '../../intake';
import './intake.css';

const ICON: Record<Format, typeof FilePDF> = { pdf: FilePDF, word: FileWord, sheet: FileCSV, json: FileJson, text: FileTxt };

/** A small tinted icon for the kind of file, from its name. */
export function FileBadge({ name }: { name: string }) {
  const format = formatOf(name);
  const Icon = ICON[format] ?? Document;
  return <span className={`in-ftype ${format}`} aria-hidden><Icon size="S" /></span>;
}

/** A coloured dot and a short word. */
export function LightView({ light }: { light: Light }) {
  return <StatusLight variant={light.tone}>{light.text}</StatusLight>;
}

/** Back to the top of the page: the main column of the shell scrolls, not the window. */
export function scrollToTop() {
  const main = document.querySelector('.main-scroll');
  if (main) main.scrollTo({ top: 0 });
  else window.scrollTo({ top: 0 });
}
