import { BrowserRouter as Router, Routes, Route, Navigate } from "react-router-dom";
import Layout from "@/components/Layout";
import Graph from "@/pages/Graph";
import QA from "@/pages/QA";
import Notes from "@/pages/Notes";
import NoteDetail from "@/pages/NoteDetail";
import Settings from "@/pages/Settings";
import Cards from "@/pages/Cards";
import CardDetail from "@/pages/CardDetail";

export default function App() {
  return (
    <Router>
      <Layout>
        <Routes>
          <Route path="/" element={<Navigate to="/graph" replace />} />
          <Route path="/graph" element={<Graph />} />
          <Route path="/qa" element={<QA />} />
          <Route path="/notes" element={<Notes />} />
          <Route path="/notes/:id" element={<NoteDetail />} />
          <Route path="/cards" element={<Cards />} />
          <Route path="/cards/:id" element={<CardDetail />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </Layout>
    </Router>
  );
}
