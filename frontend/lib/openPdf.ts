/** Opens a PDF from the API in a new tab, carrying the sign-in token. */
export async function openPdf(path: string) {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";
  const win = window.open("", "_blank");
  try {
    const token = sessionStorage.getItem("jezseem-access-token");
    const res = await fetch(`${base}${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
    if (!res.ok) {
      let detail = `Could not generate the document (${res.status}).`;
      try { detail = (await res.json()).detail ?? detail; } catch { /* no body */ }
      win?.close();
      alert(detail);
      return;
    }
    const url = URL.createObjectURL(await res.blob());
    if (win) win.location.href = url; else window.open(url, "_blank");
  } catch {
    win?.close();
    alert("Could not reach the server to generate this document.");
  }
}