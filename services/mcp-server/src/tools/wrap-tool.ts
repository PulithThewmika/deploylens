type ToolResult = { content: { type: "text"; text: string }[] };
type ToolHandler<T> = (input: T) => Promise<ToolResult>;

export function wrapTool<T>(
  toolName: string,
  handler: ToolHandler<T>,
): ToolHandler<T> {
  return async (input: T): Promise<ToolResult> => {
    try {
      return await handler(input);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : String(err);
      const stack =
        err instanceof Error ? err.stack : undefined;

      console.error(
        `[${toolName}] unhandled error: ${message}`,
        stack ?? "",
      );

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify({
              error: message,
              summary: `${toolName} failed: ${message}`,
            }),
          },
        ],
      };
    }
  };
}
