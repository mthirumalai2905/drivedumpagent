export default async function LoginPage({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  const params = await searchParams;
  return (
    <main className="login-body">
      <section className="login-card">
        <p className="eyebrow">Synx</p>
        <h1>Back Office</h1>
        <p className="lede">The mailbox is checked on its own. Sign in to see what was filed.</p>
        {params.error ? <p className="alert">Those credentials were not accepted.</p> : null}
        <form action="/api/login" method="post">
          <label htmlFor="username">Username</label>
          <input id="username" name="username" autoComplete="username" required />
          <label htmlFor="password">Password</label>
          <input id="password" name="password" type="password" autoComplete="current-password" required />
          <button type="submit">Sign in</button>
        </form>
      </section>
    </main>
  );
}
