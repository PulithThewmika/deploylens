export function parseResult(result: { content: { type: "text"; text: string }[] }): any {
  return JSON.parse(result.content[0].text);
}
