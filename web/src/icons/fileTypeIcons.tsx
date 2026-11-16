import type { ImgHTMLAttributes } from 'react';
import docxIcon from '../assets/file-icons/docx.svg';
import genericIcon from '../assets/file-icons/generic.svg';
import imageIcon from '../assets/file-icons/image.svg';
import pdfIcon from '../assets/file-icons/pdf.svg';
import pptxIcon from '../assets/file-icons/pptx.svg';
import txtIcon from '../assets/file-icons/txt.svg';
import xlsxIcon from '../assets/file-icons/xlsx.svg';

/**
 * kimi.ai FileCard glyphs (light) — vendored from public statics
 * (`Rl(ext)` map in kimi-web). White sheet + format mark; Color System
 * lives in the asset fills (#B2B2B2 / #666), not Brand accent.
 */
export type FileTypeKind = 'pdf' | 'docx' | 'xlsx' | 'pptx' | 'image' | 'text' | 'generic';

const KIND_SRC: Record<FileTypeKind, string> = {
  pdf: pdfIcon,
  docx: docxIcon,
  xlsx: xlsxIcon,
  pptx: pptxIcon,
  image: imageIcon,
  text: txtIcon,
  generic: genericIcon,
};

type FileIconProps = Omit<ImgHTMLAttributes<HTMLImageElement>, 'src' | 'alt'> & {
  size?: number;
};

function FileGlyph({ src, size = 40, ...rest }: FileIconProps & { src: string }) {
  return (
    <img src={src} alt="" width={size} height={size} draggable={false} aria-hidden {...rest} />
  );
}

export function IconFilePdf(props: FileIconProps) {
  return <FileGlyph src={KIND_SRC.pdf} {...props} />;
}

export function IconFileDocx(props: FileIconProps) {
  return <FileGlyph src={KIND_SRC.docx} {...props} />;
}

export function IconFileXlsx(props: FileIconProps) {
  return <FileGlyph src={KIND_SRC.xlsx} {...props} />;
}

export function IconFilePptx(props: FileIconProps) {
  return <FileGlyph src={KIND_SRC.pptx} {...props} />;
}

export function IconFileImage(props: FileIconProps) {
  return <FileGlyph src={KIND_SRC.image} {...props} />;
}

export function IconFilePlain(props: FileIconProps) {
  return <FileGlyph src={KIND_SRC.text} {...props} />;
}

export function IconFileGeneric(props: FileIconProps) {
  return <FileGlyph src={KIND_SRC.generic} {...props} />;
}

export function attachmentFileKind(filename: string): FileTypeKind {
  const dot = filename.lastIndexOf('.');
  const ext = dot > 0 ? filename.slice(dot).toLowerCase() : '';
  switch (ext) {
    case '.pdf':
      return 'pdf';
    case '.doc':
    case '.docx':
      return 'docx';
    case '.xls':
    case '.xlsx':
      return 'xlsx';
    case '.ppt':
    case '.pptx':
      return 'pptx';
    case '.jpg':
    case '.jpeg':
    case '.png':
    case '.webp':
    case '.gif':
      return 'image';
    case '.txt':
    case '.log':
    case '.md':
    case '.csv':
    case '.html':
    case '.htm':
      return 'text';
    default:
      return 'generic';
  }
}

export function AttachmentFileIcon({ kind, size = 40 }: { kind: FileTypeKind; size?: number }) {
  return <FileGlyph src={KIND_SRC[kind]} size={size} />;
}
