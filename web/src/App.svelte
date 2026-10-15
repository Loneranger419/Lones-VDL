<script lang="ts">
  let status = $state("checking…");

  async function loadHealth() {
    try {
      const res = await fetch("/api/health");
      if (!res.ok) {
        status = `error ${res.status}`;
        return;
      }
      const body = (await res.json()) as { status: string; version: string };
      status = `${body.status} (v${body.version})`;
    } catch {
      status = "API unreachable — start the backend on :8080";
    }
  }

  $effect(() => {
    void loadHealth();
  });
</script>

<main>
  <h1>Lones-VDL</h1>
  <p>Archive UI placeholder (Milestone 0).</p>
  <p>API health: <strong>{status}</strong></p>
</main>

<style>
  :global(body) {
    margin: 0;
    font-family: "Segoe UI", system-ui, sans-serif;
    background: #0f1419;
    color: #e7ecf1;
  }
  main {
    max-width: 40rem;
    margin: 4rem auto;
    padding: 0 1.25rem;
  }
  h1 {
    font-weight: 650;
    letter-spacing: -0.02em;
  }
</style>
