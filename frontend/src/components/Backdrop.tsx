// Decorative stand-in for a university homepage, so the helpdesk can be seen as a floating widget on a site.
// Placeholder content only: no university facts, nothing interactive (hidden from assistive tech).
// Images live in public/home/ (AI-generated illustrative photos, optimised JPEGs); replace the files to change them.
const NAV = ["About", "Admissions", "Programmes", "Campus life", "Contact"];

const CARDS = [
  { title: "Programmes", img: "/home/card-programmes.jpg" },
  { title: "Campus life", img: "/home/card-campus.jpg" },
  { title: "Admissions", img: "/home/card-admissions.jpg" },
];

export function Backdrop() {
  return (
    <div className="site" aria-hidden="true">
      <div className="site-top">Demo backdrop &middot; placeholder content &middot; not the official website</div>
      <nav className="site-nav">
        <span className="site-logo">
          <img className="site-crest" src="/christ-logo.png" alt="" />
          <span className="site-logo-text">Christ University<small>homepage demo</small></span>
        </span>
        <ul>
          {NAV.map((n) => <li key={n}>{n}</li>)}
        </ul>
      </nav>
      <section className="site-hero">
        <div className="site-hero-inner">
          <span className="site-eyebrow">Welcome</span>
          <h2>Your university homepage goes here</h2>
          <p>This page only shows where the helpdesk assistant would sit. Open the chat in the corner to try it.</p>
          <div className="site-cta"><span>Explore programmes</span><span className="ghost">Apply now</span></div>
        </div>
        <img className="site-hero-img" src="/home/hero-campus.jpg" alt="" />
      </section>
      <section className="site-cards">
        {CARDS.map((c) => (
          <div className="site-card" key={c.title}>
            <img className="site-card-img" src={c.img} alt="" />
            <h3>{c.title}</h3>
            <div className="skel skel-line" />
            <div className="skel skel-line short" />
          </div>
        ))}
      </section>
    </div>
  );
}
