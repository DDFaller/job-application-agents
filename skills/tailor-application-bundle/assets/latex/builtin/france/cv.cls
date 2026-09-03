% Original visual structure preserved from the downloaded cv.cls.
% Candidate content is supplied only by the evidence-backed renderer.
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{cv}[2026/08/21 Job Application Agents French CV]
\LoadClass[10pt,a4paper]{article}

\RequirePackage{fontspec}
\setmainfont[Path=fonts/inter/,
    Extension=.ttf,
    UprightFont=*-Light,
    BoldFont=*-SemiBold]{Inter}
\setsansfont[Path=fonts/inter/,
    Extension=.ttf,
    UprightFont=*-Light,
    BoldFont=*-SemiBold]{Inter}
\RequirePackage[compact]{titlesec}
\RequirePackage[colorlinks=true,allcolors=black]{hyperref}
\RequirePackage{fontawesome5}
\RequirePackage{mfirstuc}
\RequirePackage{parskip}
\RequirePackage[left=0cm,top=0cm,bottom=0cm,right=0cm]{geometry}
\RequirePackage{xcolor}
\RequirePackage{tikz}
\RequirePackage{adjustbox}
\RequirePackage{graphicx}
\RequirePackage{enumitem}

\definecolor{leftColor}{HTML}{D6D5CC}
\definecolor{rightColor}{HTML}{EFEFEB}
\pagenumbering{gobble}
\setlength{\parindent}{0pt}
\setlist[itemize]{leftmargin=0.45cm,itemsep=1pt,parsep=0pt,topsep=1pt}

\titleformat{\section}{\large\scshape\raggedright}{}{0em}{}[\titlerule]
\titleformat{\subsection}{\scshape\raggedright}{}{0em}{}
\titlespacing*{\section}{0pt}{5pt}{2pt}
\titlespacing*{\subsection}{0pt}{3pt}{1pt}

% Keep the visual hierarchy consistent: employers, institutions, and project
% names are bold while the optional PDF bookmark remains plain text.
\newcommand{\datesubsection}[2]{\subsection[#1]{\textbf{#1}\hfill #2}}
\newcommand{\contact}[1]{%
  \if\relax\detokenize{#1}\relax\else\parbox[t]{0.82\linewidth}{\small #1}\par\vspace{3pt}\fi
}
\newcommand{\location}[1]{%
  \if\relax\detokenize{#1}\relax\else\faMapMarker*\hspace{0.25cm}{\small #1}\par\vspace{3pt}\fi
}
\newcommand{\myitem}[2]{%
  \begin{itemize}[leftmargin=0.45cm]\item \capitalisewords{\normalsize\textbf{#1}}: #2\end{itemize}
}
\newcommand{\name}[2]{%
  \begin{center}{\LARGE\scshape #1}\end{center}
  \if\relax\detokenize{#2}\relax\else
    \begin{center}
      \begin{tikzpicture}
        \clip (0,0) circle (2.35cm);
        \node at (0,0) {\includegraphics[width=5.2cm,height=5.2cm,keepaspectratio]{#2}};
      \end{tikzpicture}
    \end{center}\vspace{2pt}
  \fi
}
\newcommand{\jobTitle}[1]{\begin{center}\Large\textbf{#1}\end{center}}
\newcommand{\cvdescription}[1]{\small #1\par\vspace{1pt}}
\newenvironment{cvitems}{\begin{itemize}}{\end{itemize}\vspace{-2pt}}
\newcommand{\cvone}[2]{\noindent\textbf{#1:} #2\par\vspace{2pt}}
\newcommand{\cvtext}[1]{\small #1\par}
