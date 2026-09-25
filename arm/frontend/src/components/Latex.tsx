import React, { useMemo } from 'react';
import katex from 'katex';
import 'katex/dist/katex.min.css';

export interface LatexProps {
  children?: string;
  math?: string;
  displayMode?: boolean;
  className?: string;
}

export const Latex: React.FC<LatexProps> = ({
  children,
  math,
  displayMode = false,
  className = '',
}) => {
  const content = math !== undefined ? math : (typeof children === 'string' ? children : '');

  const html = useMemo(() => {
    if (!content) return '';

    // Прямой рендеринг при явной передаче свойства math
    if (math !== undefined) {
      try {
        return katex.renderToString(math, {
          displayMode,
          throwOnError: false,
        });
      } catch {
        return math;
      }
    }

    // Разделение текста по блочным $$...$$ и строчным $...$ формулам
    const regex = /(\$\$[\s\S]*?\$\$|\$[^$\n]+?\$)/g;
    const parts = content.split(regex);

    return parts
      .map((part) => {
        if (part.startsWith('$$') && part.endsWith('$$')) {
          const raw = part.slice(2, -2).trim();
          try {
            return katex.renderToString(raw, {
              displayMode: true,
              throwOnError: false,
            });
          } catch {
            return part;
          }
        } else if (part.startsWith('$') && part.endsWith('$')) {
          const raw = part.slice(1, -1).trim();
          try {
            return katex.renderToString(raw, {
              displayMode: false,
              throwOnError: false,
            });
          } catch {
            return part;
          }
        } else {
          return part
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
        }
      })
      .join('');
  }, [content, math, displayMode]);

  const isBlock = displayMode || (math === undefined && content.includes('$$'));

  if (isBlock) {
    return (
      <div
        className={`latex-display overflow-x-auto py-1 ${className}`}
        dangerouslySetInnerHTML={{ __html: html }}
      />
    );
  }

  return (
    <span
      className={`latex-inline ${className}`}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
};

export default Latex;
