import { expect, test } from "vitest";

import { htmlToRichNodes, plainTextToRichNodes } from "./rich-text-paste";

test("Google Docs: opakowanie <b style=normal>, pogrubienie ze stylu, nagłówki z unikalnymi kotwicami, lista z podlistą obok pozycji", () => {
  const html = `<meta charset="utf-8"><b style="font-weight:normal;" id="docs-internal-guid-1a2b3c"><h1 dir="ltr" style="line-height:1.38;margin-top:20pt"><span style="font-size:20pt;font-weight:400;">Oferta</span></h1><p dir="ltr" style="line-height:1.38"><span style="font-size:11pt;font-weight:400;font-style:normal;">Pracujemy </span><span style="font-size:11pt;font-weight:700;">od 2010</span><span style="font-size:11pt;font-weight:400;"> roku, </span><span style="font-style:italic;font-weight:400">bez przerw</span><span style="font-weight:400">.</span></p><br><h3 dir="ltr"><span style="font-weight:400">Cennik</span></h3><ul style="margin-top:0;margin-bottom:0;"><li dir="ltr" aria-level="1"><p dir="ltr" role="presentation"><span style="font-weight:400">Pierwsza</span></p></li><ul><li aria-level="2"><p role="presentation"><span style="font-weight:400">pod</span></p></li></ul><li aria-level="1"><p role="presentation"><a href="https://example.com/cennik" style="text-decoration:none;"><span style="font-weight:400;text-decoration:underline">Druga</span></a></p></li></ul><p dir="ltr"><span style="font-weight:400">&nbsp;</span></p><h2><span>Oferta</span></h2></b>`;
  const { nodes, droppedImages } = htmlToRichNodes(html, new Set(["cennik"]));
  expect(droppedImages).toBe(false);
  expect(nodes).toEqual([
    { type: "heading", level: 2, anchor: "oferta", text: "Oferta" },
    {
      type: "paragraph",
      content: [
        { text: "Pracujemy " },
        { text: "od 2010", bold: true },
        { text: " roku, " },
        { text: "bez przerw", italic: true },
        { text: "." },
      ],
    },
    { type: "heading", level: 3, anchor: "cennik-2", text: "Cennik" },
    {
      type: "list",
      style: "bullet",
      items: [
        {
          content: [{ text: "Pierwsza" }],
          children: {
            style: "bullet",
            items: [{ content: [{ text: "pod" }] }],
          },
        },
        { content: [{ text: "Druga", href: "https://example.com/cennik" }] },
      ],
    },
    { type: "heading", level: 2, anchor: "oferta-2", text: "Oferta" },
  ]);
});

test("Word: akapity MsoListParagraph stają się listą, znacznik punktu i komentarze warunkowe znikają", () => {
  const html = `<html xmlns:o="urn:schemas-microsoft-com:office:office"><head><style>p.MsoNormal{margin:0}</style></head><body lang=PL>
<!--StartFragment--><p class=MsoNormal><b><span style='font-size:12.0pt'>Ważne:</span></b><span style='font-size:12.0pt'> przed wizytą <i>przygotuj</i> dokumenty.<o:p></o:p></span></p>
<p class=MsoListParagraphCxSpFirst style='text-indent:-18.0pt;mso-list:l0 level1 lfo1'><![if !supportLists]><span style='font-family:Symbol;mso-list:Ignore'>·<span style='font:7.0pt "Times New Roman"'>&nbsp;&nbsp;&nbsp; </span></span><![endif]>dowód osobisty<o:p></o:p></p>
<p class=MsoListParagraphCxSpLast style='text-indent:-18.0pt;mso-list:l0 level1 lfo1'><![if !supportLists]><span style='mso-list:Ignore'>·<span>&nbsp;&nbsp; </span></span><![endif]>skierowanie<o:p></o:p></p>
<p class=MsoNormal><o:p>&nbsp;</o:p></p>
<p class=MsoListParagraphCxSpFirst><span style='mso-list:Ignore'>1.<span>&nbsp; </span></span>zadzwoń</p>
<table class=MsoTableGrid><tr><td><p class=MsoNormal>Pon</p></td><td><p class=MsoNormal><b>8–16</b></p></td></tr><tr><td>Wt</td><td></td></tr></table>
<blockquote><p>Najlepsza <em>obsługa</em></p><p>w mieście</p></blockquote><!--EndFragment--></body></html>`;
  expect(htmlToRichNodes(html).nodes).toEqual([
    {
      type: "paragraph",
      content: [
        { text: "Ważne:", bold: true },
        { text: " przed wizytą " },
        { text: "przygotuj", italic: true },
        { text: " dokumenty." },
      ],
    },
    {
      type: "list",
      style: "bullet",
      items: [
        { content: [{ text: "dowód osobisty" }] },
        { content: [{ text: "skierowanie" }] },
      ],
    },
    {
      type: "list",
      style: "ordered",
      items: [{ content: [{ text: "zadzwoń" }] }],
    },
    {
      type: "paragraph",
      content: [{ text: "Pon – " }, { text: "8–16", bold: true }],
    },
    { type: "paragraph", content: [{ text: "Wt" }] },
    {
      type: "quote",
      content: [
        { text: "Najlepsza " },
        { text: "obsługa", italic: true },
        { text: " w mieście" },
      ],
    },
  ]);
});

test("usuwa obrazy, skrypty i style, zgłasza pominięte obrazy i odrzuca niedozwolone adresy", () => {
  const { nodes, droppedImages } = htmlToRichNodes(
    `<p>Tekst <img src="x.png" alt="zdjęcie"> dalej<script>alert(1)</script><style>p{}</style></p><iframe src="https://evil"></iframe><figure><img src="y.png"><figcaption>Podpis</figcaption></figure><p><a href="javascript:alert(1)">klik</a> <a href="//evil.example">tu</a> <a href="mailto:biuro@example.com">mail</a> <a>bez</a></p><h4>Mały</h4><h6>Najmniejszy</h6><p>   </p><div>luźny <strong>tekst</strong><p>w divie</p>ogon</div>`,
  );
  expect(droppedImages).toBe(true);
  expect(nodes).toEqual([
    { type: "paragraph", content: [{ text: "Tekst dalej" }] },
    { type: "paragraph", content: [{ text: "Podpis" }] },
    {
      type: "paragraph",
      content: [
        { text: "klik tu " },
        { text: "mail", href: "mailto:biuro@example.com" },
        { text: " bez" },
      ],
    },
    { type: "heading", level: 4, anchor: "maly", text: "Mały" },
    { type: "heading", level: 4, anchor: "najmniejszy", text: "Najmniejszy" },
    {
      type: "paragraph",
      content: [{ text: "luźny " }, { text: "tekst", bold: true }],
    },
    { type: "paragraph", content: [{ text: "w divie" }] },
    { type: "paragraph", content: [{ text: "ogon" }] },
  ]);
  expect(htmlToRichNodes("<p>a<br>b</p>").nodes).toEqual([
    { type: "paragraph", content: [{ text: "a b" }] },
  ]);
  expect(
    htmlToRichNodes("<ol><li>a<ol><li>b<ul><li>c</li></ul></li></ol></li></ol>")
      .nodes,
  ).toEqual([
    {
      type: "list",
      style: "ordered",
      items: [
        {
          content: [{ text: "a" }],
          children: {
            style: "ordered",
            items: [{ content: [{ text: "b" }] }, { content: [{ text: "c" }] }],
          },
        },
      ],
    },
  ]);
});

test("limity kontraktu: najwyżej 160 węzłów, długi tekst dzielony na przebiegi, za długi nagłówek zostaje akapitem", () => {
  const many = Array.from(
    { length: 200 },
    (_, index) => `<p>${index}</p>`,
  ).join("");
  const { nodes } = htmlToRichNodes(many);
  expect(nodes).toHaveLength(160);
  const long = htmlToRichNodes(`<p>${"x".repeat(9000)}</p>`).nodes[0];
  expect(long).toEqual({
    type: "paragraph",
    content: [
      { text: "x".repeat(4000) },
      { text: "x".repeat(4000) },
      { text: "x".repeat(1000) },
    ],
  });
  const heading = "Słowo ".repeat(40).trim();
  expect(htmlToRichNodes(`<h2>${heading}</h2>`).nodes).toEqual([
    { type: "paragraph", content: [{ text: heading }] },
  ]);
  expect(
    plainTextToRichNodes(Array.from({ length: 170 }, String).join("\n\n")),
  ).toHaveLength(160);
});

test("zwykły tekst: akapity po pustych liniach, listy z myślników i numerów, gwiazdki zostają tekstem", () => {
  expect(
    plainTextToRichNodes(
      "Pierwszy akapit\nw dwóch wierszach\r\n\r\n  \nZakres:\n- projekt\n  1. szkic\n* wdrożenie **teraz**\n\n1. jeden\n2) dwa\n\n2*3*4 to działanie",
    ),
  ).toEqual([
    {
      type: "paragraph",
      content: [{ text: "Pierwszy akapit\nw dwóch wierszach" }],
    },
    { type: "paragraph", content: [{ text: "Zakres:" }] },
    {
      type: "list",
      style: "bullet",
      items: [
        {
          content: [{ text: "projekt" }],
          children: {
            style: "ordered",
            items: [{ content: [{ text: "szkic" }] }],
          },
        },
        { content: [{ text: "wdrożenie **teraz**" }] },
      ],
    },
    {
      type: "list",
      style: "ordered",
      items: [{ content: [{ text: "jeden" }] }, { content: [{ text: "dwa" }] }],
    },
    { type: "paragraph", content: [{ text: "2*3*4 to działanie" }] },
  ]);
  expect(plainTextToRichNodes("\n\n  \n")).toEqual([]);
});
