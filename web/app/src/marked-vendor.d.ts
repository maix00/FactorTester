declare module "*vendor/marked/marked.min.js" {
  class Marked {
    use(options: Record<string, unknown>): void;
    parse(source: string, options?: Record<string, unknown>): string;
  }
  const marked: { parse(source: string, options?: Record<string, unknown>): string; Marked: typeof Marked };
  export default marked;
}
