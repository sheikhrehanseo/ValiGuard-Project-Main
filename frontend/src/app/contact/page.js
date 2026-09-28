
"use client";

import { motion } from 'framer-motion';
import { Mail, Send, ArrowLeft, Github, Twitter, MessageCircle } from 'lucide-react';
import Link from 'next/link';

export default function ContactPage() {
    return (
        <div className="min-h-screen bg-slate-900 text-white flex items-center justify-center p-4 relative overflow-hidden">
            {/* Background Blobs */}
            <div className="absolute top-0 left-0 w-96 h-96 bg-blue-600/20 rounded-full blur-3xl -translate-x-1/2 -translate-y-1/2 pointer-events-none" />
            <div className="absolute bottom-0 right-0 w-96 h-96 bg-purple-600/20 rounded-full blur-3xl translate-x-1/2 translate-y-1/2 pointer-events-none" />

            <motion.div
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                className="bg-slate-800/80 backdrop-blur-xl border border-slate-700/50 p-8 rounded-2xl shadow-2xl max-w-lg w-full z-10"
            >
                <Link href="/" className="inline-flex items-center text-slate-400 hover:text-white transition-colors mb-6 text-sm">
                    <ArrowLeft className="w-4 h-4 mr-2" /> Back to Dashboard
                </Link>

                <h1 className="text-3xl font-bold mb-2 bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-purple-400">Get in Touch</h1>
                <p className="text-slate-400 mb-8">Have questions or need support? Drop us a message.</p>

                <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); alert('Message sent!'); }}>
                    <div className="space-y-1">
                        <label className="text-xs font-semibold text-slate-500 uppercase">Email Address</label>
                        <div className="relative">
                            <Mail className="absolute left-3 top-3 w-5 h-5 text-slate-500" />
                            <input type="email" required placeholder="you@example.com" className="w-full bg-slate-900/50 border border-slate-700 rounded-lg py-2.5 pl-10 pr-4 focus:ring-2 focus:ring-blue-500 outline-none transition-all placeholder:text-slate-600" />
                        </div>
                    </div>

                    <div className="space-y-1">
                        <label className="text-xs font-semibold text-slate-500 uppercase">Message</label>
                        <textarea required rows="4" placeholder="How can we help?" className="w-full bg-slate-900/50 border border-slate-700 rounded-lg p-4 focus:ring-2 focus:ring-blue-500 outline-none transition-all placeholder:text-slate-600 resize-none"></textarea>
                    </div>

                    <button className="w-full bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white font-semibold py-3 rounded-lg shadow-lg shadow-blue-600/20 flex items-center justify-center gap-2 transition-all transform active:scale-95">
                        <Send className="w-4 h-4" />
                        Send Message
                    </button>
                </form>

                <div className="mt-8 pt-6 border-t border-slate-700/50 flex justify-center gap-6">
                    <SocialLink icon={Github} href="#" />
                    <SocialLink icon={Twitter} href="#" />
                    <SocialLink icon={MessageCircle} href="#" />
                </div>
            </motion.div>
        </div>
    );
}

function SocialLink({ icon: Icon, href }) {
    return (
        <a href={href} className="text-slate-500 hover:text-white transition-colors p-2 hover:bg-slate-700/50 rounded-full">
            <Icon className="w-5 h-5" />
        </a>
    );
}
