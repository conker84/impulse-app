import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import * as api from "./api";

/** Build a Response-like stub for the global fetch mock. */
function jsonResponse(body: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: async () => body,
    text: async () => (typeof body === "string" ? body : JSON.stringify(body)),
  } as Response;
}

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("request wrapper (via sendChat)", () => {
  it("prefixes /api, POSTs JSON, and sets the content-type header", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ session_id: "s1" }));
    await api.sendChat("hello", "s1");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/chat");
    expect(init.method).toBe("POST");
    expect(init.headers).toMatchObject({ "Content-Type": "application/json" });
    expect(JSON.parse(init.body)).toEqual({ message: "hello", session_id: "s1" });
  });

  it("returns the parsed JSON body", async () => {
    const payload = { session_id: "abc", message: { role: "assistant", content: "hi" } };
    fetchMock.mockResolvedValueOnce(jsonResponse(payload));
    const res = await api.sendChat("hi", null);
    expect(res).toEqual(payload);
  });

  it("passes a null session_id through unchanged", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({}));
    await api.sendChat("hi", null);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      message: "hi",
      session_id: null,
    });
  });

  it("throws '<status>: <body>' on a non-ok response", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse("boom", false, 500));
    await expect(api.sendChat("x", null)).rejects.toThrow("500: boom");
  });
});

describe("URL building + encoding", () => {
  it("getState interpolates the session id into the path", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({}));
    await api.getState("sess-123");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/state/sess-123");
  });

  it("listSchemas url-encodes the catalog query param", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ schemas: [] }));
    await api.listSchemas("my catalog/weird");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/uc/schemas?catalog=my%20catalog%2Fweird");
  });

  it("listVolumes encodes both catalog and schema", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ volumes: [] }));
    await api.listVolumes("c a", "s&b");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/uc/volumes?catalog=c%20a&schema=s%26b");
  });

  it("fetchTimeSeriesData appends x_min/x_max only when provided", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: [], total_points: 0 }));

    await api.fetchTimeSeriesData("cat", "sch", 1, 2);
    expect(fetchMock.mock.calls[0][0]).not.toContain("x_min");
    expect(fetchMock.mock.calls[0][0]).not.toContain("x_max");

    await api.fetchTimeSeriesData("cat", "sch", 1, 2, 10, 20, 100);
    const url = fetchMock.mock.calls[1][0];
    expect(url).toContain("n_points=100");
    expect(url).toContain("x_min=10");
    expect(url).toContain("x_max=20");
  });
});

describe("setSourceData", () => {
  it("hits the no-session endpoint and fills defaults when sessionId is null", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ session_id: "new" }));
    await api.setSourceData(null, "existing", { silver_catalog: "c" });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/set-source-data");
    expect(JSON.parse(init.body)).toEqual({
      mode: "existing",
      silver_catalog: "c",
      silver_schema: "",
      upload_catalog: "",
      upload_schema: "",
      upload_volume: "",
    });
  });

  it("hits the session-scoped endpoint when a sessionId is given", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({}));
    await api.setSourceData("s9", "upload");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/set-source-data/s9");
  });
});

describe("uploadMf4Files", () => {
  it("sends multipart FormData without a JSON content-type", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ uploaded: ["a.mf4"], errors: [] }));
    const files = [
      new File(["x"], "a.mf4"),
      new File(["y"], "b.mf4"),
    ] as unknown as FileList;
    // give it a length + indexable access like a real FileList
    (files as any).length = 2;

    const res = await api.uploadMf4Files("sess", files);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/upload-mf4/sess");
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
    expect(init.headers).toBeUndefined(); // must let the browser set the boundary
    expect((init.body as FormData).getAll("files")).toHaveLength(2);
    expect(res.uploaded).toEqual(["a.mf4"]);
  });

  it("throws on non-ok upload", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse("too big", false, 413));
    const files = [new File(["x"], "a.mf4")] as unknown as FileList;
    (files as any).length = 1;
    await expect(api.uploadMf4Files("s", files)).rejects.toThrow("413: too big");
  });
});

describe("loadTimeSeriesChannels polling", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("returns immediately when the initial response is already done", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ status: "done", channels: [] }));
    const res = await api.loadTimeSeriesChannels("c", "s", 1, [10, 11]);
    expect(res).toMatchObject({ status: "done" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    // verify the POST payload mapping (schema -> schema_name)
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      catalog: "c",
      schema_name: "s",
      container_id: 1,
      channel_ids: [10, 11],
    });
  });

  it("polls until status=done, reporting progress on each loading tick", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ status: "loading", load_id: "L1" }))
      .mockResolvedValueOnce(jsonResponse({ status: "loading", message: "working", elapsed_ms: 1000 }))
      .mockResolvedValueOnce(jsonResponse({ status: "done", channels: [{ id: 1 }] }));

    const onProgress = vi.fn();
    const promise = api.loadTimeSeriesChannels("c", "s", 1, [1], onProgress);
    // advance through the two 1s poll waits
    await vi.advanceTimersByTimeAsync(1000);
    await vi.advanceTimersByTimeAsync(1000);
    const res = await promise;

    expect(res).toMatchObject({ status: "done" });
    expect(onProgress).toHaveBeenCalledWith("working", 1000);
    expect(fetchMock.mock.calls[1][0]).toBe("/api/timeseries/load/status/L1");
  });

  it("rejects when polling reports an error status", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ status: "loading", load_id: "L2" }))
      .mockResolvedValueOnce(jsonResponse({ status: "error", error: "load failed" }));

    const promise = api.loadTimeSeriesChannels("c", "s", 1, [1]);
    const assertion = expect(promise).rejects.toThrow("load failed");
    await vi.advanceTimersByTimeAsync(1000);
    await assertion;
  });
});

describe("resampleTimeSeries", () => {
  it("posts cache keys + window + flags", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ traces: [] }));
    await api.resampleTimeSeries(["k1", "k2"], 100, 200, 3000, true);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/timeseries/resample");
    expect(JSON.parse(init.body)).toEqual({
      cache_keys: ["k1", "k2"],
      x_min_ns: 100,
      x_max_ns: 200,
      n_points: 3000,
      normalize: true,
    });
  });

  it("passes null window bounds through unchanged", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ traces: [] }));
    await api.resampleTimeSeries(["k1"], null, null);
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.x_min_ns).toBeNull();
    expect(body.x_max_ns).toBeNull();
    expect(body.n_points).toBe(5000); // default
    expect(body.normalize).toBe(false); // default
  });
});

describe("sendFeedback", () => {
  it("POSTs trace_id, positive and optional comment to /api/feedback", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ recorded: true }));
    const res = await api.sendFeedback("tr-123", true, "great answer");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/feedback");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ trace_id: "tr-123", positive: true, comment: "great answer" });
    expect(res).toEqual({ recorded: true });
  });
});
