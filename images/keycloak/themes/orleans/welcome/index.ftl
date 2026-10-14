<#ftl output_format="HTML" auto_esc=true>
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="color-scheme" content="light dark">
    <title>Orleans sign-in</title>
    <style>
      :root { font-family: system-ui, sans-serif; color-scheme: light dark; }
      body { margin: 0; padding: 2rem 1rem; background: light-dark(#f4f5f6, #151719); color: light-dark(#202428, #f2f4f5); }
      main { box-sizing: border-box; max-width: 30rem; margin: 4rem auto; padding: 2rem; border-radius: 0.75rem; background: light-dark(#fff, #23272b); }
      h1 { margin-top: 0; font-size: 1.75rem; }
      h2 { margin: 2rem 0 0.75rem; font-size: 1rem; }
      p { line-height: 1.5; }
      a { color: light-dark(#145a9c, #9acbff); text-underline-offset: 0.2em; }
      .sign-in { display: block; padding: 0.85rem 1rem; border-radius: 0.35rem; background: light-dark(#145a9c, #9acbff); color: light-dark(#fff, #10243a); text-align: center; text-decoration: none; font-weight: 600; }
      ul { display: grid; gap: 1rem; list-style: none; padding: 0; margin-bottom: 0; }
      li p { margin: 0.3rem 0 0; font-size: 0.9rem; }
      a:focus-visible { outline: 3px solid light-dark(#145a9c, #9acbff); outline-offset: 4px; }
      @media (max-width: 400px) { main { margin: 1rem auto; padding: 1.5rem; } }
    </style>
  </head>
  <body>
    <main>
      <h1>Welcome to Orleans</h1>
      <#if bootstrap>
        <p>Initial server setup is required. Create an administrator using Keycloak's <code>bootstrap-admin</code> command before signing in.</p>
      <#else>
        <p>Sign in to manage your Sequoia account.</p>
        <a class="sign-in" href="${baseUrl}realms/sequoia/account/">Sign in to Sequoia</a>
        <#if adminConsoleEnabled>
          <nav aria-label="Administration">
            <h2>Administration</h2>
            <ul>
              <li>
                <a href="${baseUrl}admin/sequoia/console/">Manage Sequoia</a>
                <p>Sequoia administration console.</p>
              </li>
              <li>
                <a href="${baseUrl}admin/master/console/">Manage master realm</a>
                <p>master realm administration console.</p>
              </li>
            </ul>
          </nav>
        </#if>
      </#if>
    </main>
  </body>
</html>
