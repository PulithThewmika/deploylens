import { describe, it, expect, vi } from "vitest";
import { wrapTool } from "./wrap-tool.js";

describe("wrapTool", () => {
  it("passes through successful results unchanged", async () => {
    const handler = async () => ({
      content: [{ type: "text" as const, text: '{"summary":"ok"}' }],
    });

    const wrapped = wrapTool("test_tool", handler);
    const result = await wrapped({ foo: 1 });

    expect(JSON.parse(result.content[0].text)).toEqual({ summary: "ok" });
    expect(result.isError).toBeUndefined();
  });

  it("catches thrown errors and returns structured error response", async () => {
    const handler = async () => {
      throw new Error("connection refused");
    };

    const wrapped = wrapTool("query_metrics", handler);
    const result = await wrapped({});
    const parsed = JSON.parse(result.content[0].text);

    expect(parsed.error).toBe("connection refused");
    expect(parsed.summary).toBe("query_metrics failed: connection refused");
    expect(result.isError).toBe(true);
  });

  it("handles non-Error throws", async () => {
    const handler = async () => {
      throw "string error";
    };

    const wrapped = wrapTool("my_tool", handler);
    const result = await wrapped({});
    const parsed = JSON.parse(result.content[0].text);

    expect(parsed.error).toBe("string error");
    expect(parsed.summary).toBe("my_tool failed: string error");
  });

  it("logs errors to stderr with stack trace", async () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    const err = new Error("db timeout");

    const handler = async () => { throw err; };
    const wrapped = wrapTool("get_deployment", handler);
    await wrapped({});

    expect(spy).toHaveBeenCalledWith(
      "[get_deployment] unhandled error: db timeout",
      err.stack,
    );

    spy.mockRestore();
  });

  it("forwards input to the handler", async () => {
    const handler = vi.fn(async (input: { id: number }) => ({
      content: [{ type: "text" as const, text: JSON.stringify({ id: input.id }) }],
    }));

    const wrapped = wrapTool("test", handler);
    await wrapped({ id: 42 });

    expect(handler).toHaveBeenCalledWith({ id: 42 });
  });
});
