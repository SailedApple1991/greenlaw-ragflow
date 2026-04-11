import { useEffect, useRef, useState } from 'react';

const TICK_MS = 30;

/**
 * Progressively reveals content, creating a word-by-word typing effect.
 *
 * - Content present on mount is shown immediately (historical messages).
 * - Content that arrives after mount (streaming or cache hit) is animated.
 * - Adaptive speed: catches up fast for large chunks, slows down at the tail.
 */
export function useTypewriter(content: string): string {
  // Initialise to current length so historical messages render instantly
  const [displayedLength, setDisplayedLength] = useState(() => content.length);
  const contentRef = useRef(content);
  contentRef.current = content;

  // Snap down if content ever shrinks (edge case)
  useEffect(() => {
    if (displayedLength > content.length) {
      setDisplayedLength(content.length);
    }
  }, [displayedLength, content.length]);

  const needsAnimation = displayedLength < content.length;

  useEffect(() => {
    if (!needsAnimation) return;

    const id = setInterval(() => {
      setDisplayedLength((prev) => {
        const len = contentRef.current.length;
        if (prev >= len) return prev;
        const gap = len - prev;
        // Adaptive step: fast catch-up for big gaps, slower reveal at the end
        const step = gap > 500 ? 20 : gap > 100 ? 8 : 3;
        return Math.min(prev + step, len);
      });
    }, TICK_MS);

    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [needsAnimation]);

  if (displayedLength >= content.length) return content;
  return content.slice(0, displayedLength);
}
