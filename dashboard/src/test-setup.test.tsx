// Guards the async drain in test-setup.ts: React flushes passive effects through
// the scheduler's setImmediate, and testing-library's findBy* drains with
// setTimeout(0); Bun does not order the two, so without the extra drain an effect
// that runs after the element appears could still be pending when findBy resolves.
import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, render, screen } from "@testing-library/react";
import { useEffect, useState } from "react";

afterEach(cleanup);

function Loader({ onStage }: { onStage: (stage: string) => void }) {
  const [stage, setStage] = useState("");
  useEffect(() => {
    void Promise.resolve("plan").then(setStage);
  }, []);
  useEffect(() => {
    if (stage) onStage(stage);
  }, [stage, onStage]);
  return stage ? <button type="button">{stage}</button> : null;
}

test.each(Array.from({ length: 500 }, (_, index) => index))(
  "an effect of the render that showed an element has run when findBy resolves (%i)",
  async () => {
    const onStage = mock(() => {});
    render(<Loader onStage={onStage} />);
    await screen.findByRole("button", { name: "plan" });
    expect(onStage).toHaveBeenCalledTimes(1);
  },
);
