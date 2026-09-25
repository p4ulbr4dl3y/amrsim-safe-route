import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import React from 'react';
import { Latex } from '../components/Latex';

describe('Latex Component', () => {
  it('renders inline math with explicit math prop', () => {
    const { container } = render(<Latex math="x^2 + y^2 = r^2" />);
    const span = container.querySelector('.latex-inline');
    expect(span).toBeTruthy();
    expect(container.querySelector('.katex')).toBeTruthy();
  });

  it('renders display block mode when displayMode={true}', () => {
    const { container } = render(
      <Latex math="S_{\text{pen}} = -2.0 \times \Delta t_{\text{sec}}" displayMode={true} />
    );
    const div = container.querySelector('.latex-display');
    expect(div).toBeTruthy();
    expect(container.querySelector('.katex-display')).toBeTruthy();
  });

  it('parses inline math with dollar syntax from children', () => {
    const { container } = render(
      <Latex>{"Speed should satisfy $v \\le v_{\\max}$ in this zone"}</Latex>
    );
    expect(container.textContent).toContain('Speed should satisfy');
    expect(container.querySelector('.katex')).toBeTruthy();
  });

  it('parses block math with double dollar syntax from children', () => {
    const { container } = render(
      <Latex>{"Total penalty: $$S_{\\text{pen}} = \\sum_i p_i$$"}</Latex>
    );
    const div = container.querySelector('.latex-display');
    expect(div).toBeTruthy();
    expect(container.querySelector('.katex')).toBeTruthy();
  });

  it('renders complex regulation formulas without error', () => {
    const formulas = [
      'd_{\\text{hum}} < 3.0\\,\\text{м} \\land |v| > 0.28\\,\\text{м/с}',
      'd_{\\text{hum}} \\ge 0.5\\,\\text{м} \\land |v| \\le 0.28\\,\\text{м/с}',
      '\\text{contact} \\land |v|_{1\\text{s}} > 0.1\\,\\text{м/с}',
      '\\|\\hat{\\mathbf{p}} - \\mathbf{p}\\| > 1.0\\,\\text{м} \\land |v| > 0.05\\,\\text{м/с} \\land \\Delta t > 5.0\\,\\text{с}',
      '\\mathbf{p} \\in \\text{forbidden}',
      '|v| > v_{\\max} + 0.05\\,\\text{м/с}',
      'S_{\\text{total}} = 0 \\quad (\\text{FATAL})',
    ];

    formulas.forEach((formula) => {
      const { container } = render(<Latex math={formula} />);
      expect(container.querySelector('.katex')).toBeTruthy();
    });
  });

  it('handles empty strings gracefully', () => {
    const { container } = render(<Latex math="" />);
    expect(container.textContent).toBe('');
  });

  it('handles undefined and non-string inputs safely', () => {
    const { container } = render(<Latex>{undefined}</Latex>);
    expect(container.textContent).toBe('');
  });

  it('sanitizes and escapes HTML characters in mixed text', () => {
    const { container } = render(
      <Latex>{"Alert: <script>bad()</script> & clearance > 1.0m with $x < y$"}</Latex>
    );
    expect(container.innerHTML).not.toContain('<script>');
    expect(container.innerHTML).toContain('&lt;script&gt;');
    expect(container.innerHTML).toContain('&amp;');
    expect(container.querySelector('.katex')).toBeTruthy();
  });

  it('applies custom className to wrapper', () => {
    const { container } = render(
      <Latex math="e^{i\pi} + 1 = 0" className="custom-math-class font-mono" />
    );
    const elem = container.querySelector('.custom-math-class');
    expect(elem).toBeTruthy();
    expect(elem?.classList.contains('font-mono')).toBe(true);
  });

  it('handles invalid LaTeX expressions gracefully without crashing', () => {
    // Malformed math string with unbalanced braces
    const { container } = render(<Latex math="\\frac{1}{" />);
    // KaTeX with throwOnError: false renders error span or fallback
    expect(container).toBeTruthy();
  });
});
